"""双击单词气泡 → 打开中文详情（2026-09-29）回归测试。

覆盖三层不变式：

- **模式与穿透**：单词气泡显示期间接收鼠标（可双击），情绪气泡 / 隐藏态
  保持全穿透（鼠标落到下层，双击天然无效）。
- **信号**：单词态双击 → ``word_detail_requested`` 携带词条发出；情绪态 /
  空词条不发。
- **controller 处置**：双击处理 = 记入生词本（学习闭环）+ 打开详情窗口，
  且气泡 / 按钮条同步隐藏、下一词排期推进。

全部使用 ``QT_QPA_PLATFORM=offscreen``。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.core.word_detail import WordDetail
from desktop_pet.ui.bubble import BubbleWindow

_ENTRY = VocabEntry(
    id="n5-001", level="N5", word="猫", kana="ねこ",
    translation="猫", meaning="一种常见的宠物", romaji="neko",
)


# --------------------------------------------------------------------------- #
# 1. 模式与穿透
# --------------------------------------------------------------------------- #
def test_word_bubble_captures_mouse(qtbot) -> None:
    """单词气泡显示期间解除穿透（可接收双击）。"""

    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(100, 100))
    bubble.show_word(_ENTRY, C.JP_BUBBLE_MIN_DURATION_S)
    qtbot.waitUntil(bubble.isVisible)
    assert bubble._mode == 1  # _MODE_WORD
    assert bubble._word_entry is _ENTRY
    assert not bubble.windowFlags() & Qt.WindowType.WindowTransparentForInput, (
        "单词气泡应解除输入穿透（否则双击落到下层）"
    )
    assert not bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_message_bubble_stays_transparent(qtbot) -> None:
    """情绪气泡保持全穿透（双击天然无效，也不挡下层点击）。"""

    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(100, 100))
    bubble.show_message("嘿嘿~", 2.0)
    qtbot.waitUntil(bubble.isVisible)
    assert bubble._word_entry is None
    assert bubble.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)


def test_word_to_message_switch_restores_transparency(qtbot) -> None:
    """单词气泡显示中被情绪气泡覆盖 → 穿透恢复、词条清空（双击不再生效）。"""

    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(100, 100))
    bubble.show_word(_ENTRY, C.JP_BUBBLE_MIN_DURATION_S)
    qtbot.waitUntil(bubble.isVisible)
    bubble.show_message("被覆盖啦~", 2.0)
    assert bubble._word_entry is None
    assert bubble.windowFlags() & Qt.WindowType.WindowTransparentForInput


def test_hide_bubble_resets_entry_and_transparency(qtbot) -> None:
    """隐藏气泡复位词条引用与穿透态（下次情绪气泡零成本）。"""

    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(100, 100))
    bubble.show_word(_ENTRY, C.JP_BUBBLE_MIN_DURATION_S)
    qtbot.waitUntil(bubble.isVisible)
    bubble.hide_bubble()
    assert bubble._word_entry is None
    assert bubble.windowFlags() & Qt.WindowType.WindowTransparentForInput


# --------------------------------------------------------------------------- #
# 2. 双击信号
# --------------------------------------------------------------------------- #
def test_double_click_word_bubble_emits_entry(qtbot) -> None:
    """单词态双击 → word_detail_requested 携带词条发出。"""

    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(100, 100))
    bubble.show_word(_ENTRY, C.JP_BUBBLE_MIN_DURATION_S)
    with qtbot.waitSignal(bubble.word_detail_requested, timeout=2000) as blocker:
        bubble._emit_word_detail_if_word_mode()
    assert blocker.args[0] is _ENTRY


def test_double_click_message_bubble_is_silent(qtbot) -> None:
    """情绪态（即使被强行模拟事件）不发信号 —— 只单词气泡有效。"""

    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(100, 100))
    bubble.show_message("情绪台词~", 2.0)
    received: list[object] = []
    bubble.word_detail_requested.connect(received.append)
    bubble._emit_word_detail_if_word_mode()
    assert received == [], "情绪气泡双击必须无效"


def test_double_click_after_hide_is_silent(qtbot) -> None:
    """气泡已隐藏（词条复位）→ 双击不发信号。"""

    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(100, 100))
    bubble.show_word(_ENTRY, C.JP_BUBBLE_MIN_DURATION_S)
    bubble.hide_bubble()
    received: list[object] = []
    bubble.word_detail_requested.connect(received.append)
    bubble._emit_word_detail_if_word_mode()
    assert received == []


# --------------------------------------------------------------------------- #
# 3. controller 处置闭环（记生词 + 打开详情）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """最小 controller：store 指向 tmp_path（与 test_bubble_trigger_rhythm 同范式）。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._mastered = MasteredStore(tmp_path / "mastered.json")
    ctrl._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    ctrl._vocab = VocabStore(tmp_path / "vocab.json")
    ctrl._mastered.load()
    ctrl._daily_log.load()
    ctrl._vocab.load()

    ctrl._today_str = "2025-01-01"
    return ctrl


def test_controller_disposes_vocab_and_opens_detail(
    qtbot, controller: PetAppController
) -> None:
    """双击处理 = 生词本入库 + 详情窗口打开 + 下一词排期推进。"""

    entry = _ENTRY
    controller._current_word = entry
    controller._word_disposed = False

    detail = WordDetail(
        meaning_zh=(entry.meaning,),
        pos_zh=(),
        collocations=(),
        examples=(),
        usage_note_zh="",
    )
    with patch.object(controller, "_lookup_word_detail", return_value=(detail, "bank")), \
         patch.object(controller, "_detail_net_config", return_value=None):
        controller._on_bubble_word_detail(entry)

    # 生词本入库
    ids = [item.id for item in controller._vocab.items()]
    assert entry.id in ids, "双击查看详情的词应记入生词本"
    # 单飞状态复位 + 下一词已排期
    assert controller._current_word is None
    assert controller._word_disposed is True
    # 详情窗口单例已打开并展示词条
    assert controller._detail_window is not None
    qtbot.addWidget(controller._detail_window)


def test_controller_ignores_detail_when_no_current_word(
    qtbot, controller: PetAppController
) -> None:
    """无当前展示词（已处置 / 从未展示）→ 双击处理静默 no-op。"""

    controller._current_word = None
    controller._word_disposed = True
    received: list[object] = []
    controller._bubble.word_detail_requested.connect(received.append)

    controller._on_bubble_word_detail(_ENTRY)

    assert controller._vocab.items() == [], "无当前词不应入库"
    assert controller._detail_window is None, "无当前词不应打开详情窗"
    assert received == []
