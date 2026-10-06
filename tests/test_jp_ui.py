"""日语学习 UI 冒烟（气泡多行渲染 / 托盘菜单 / 生词本窗口）。

使用 ``qtbot``（``conftest.py`` 已设 ``QT_QPA_PLATFORM=offscreen``），**不弹真实窗口**。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint
from PySide6.QtGui import QIcon

from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig
from desktop_pet.core.vocab_store import VocabItem
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.ui.bubble import BubbleWindow
from desktop_pet.ui.tray import TrayController
from desktop_pet.ui.vocab_window import VocabWindow


def _entry() -> VocabEntry:
    return VocabEntry(
        id="n5-0001", level="N5", word="私", kana="わたし",
        translation="我", meaning="第一人称代词", romaji="watashi",
    )


def _item(i: int, level: str = "N5") -> VocabItem:
    return VocabItem(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}",
        kana="かな", translation="译", meaning="义", added_at="2025-01-01T00:00:00Z",
    )


# --------------------------------------------------------------------------- #
# 1. 学习泡泡（气泡多行渲染）
# --------------------------------------------------------------------------- #
def test_show_word_sets_mode_and_fixed_width(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 3.0)

    assert bubble._mode == 1, "未进入单词模式"
    assert bubble._line_word == "私"
    assert bubble._line_kana == "わたし"
    assert bubble._line_translation == "我"
    assert bubble._line_meaning == "第一人称代词"

    expected_w = int(round(
        C.JP_BUBBLE_MAX_WIDTH + C.BUBBLE_PAD_X * 2.0 + C.BUBBLE_STROKE_MARGIN * 2.0
    ))
    assert bubble.width() == expected_w, "学习泡泡内容宽度未按 JP_BUBBLE_MAX_WIDTH 固定"

    measured = bubble._measure_word()
    assert bubble.height() >= int(round(measured.height() + C.BUBBLE_PAD_Y * 2.0))
    bubble.hide_bubble()


def test_show_message_resets_to_text_mode(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 3.0)
    bubble.show_message("你好呀~", 2.0)
    assert bubble._mode == 0
    assert bubble._text == "你好呀~"
    bubble.hide_bubble()


def test_show_word_none_is_noop(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.show_message("keep", 2.0)
    bubble.show_word(None, 3.0)  # 空 entry → no-op
    assert bubble._text == "keep"
    assert bubble._mode == 0
    bubble.hide_bubble()


def test_word_layout_uses_max_width(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 3.0)
    layout = bubble._word_layout(C.JP_BUBBLE_MAX_WIDTH)
    assert len(layout) == 4, "四行布局缺失"
    assert bubble._font_word.bold() is True
    assert bubble._font_word.pointSize() == C.JP_BUBBLE_WORD_FONT_SIZE
    bubble.hide_bubble()


# --------------------------------------------------------------------------- #
# 2. 托盘日语菜单
# --------------------------------------------------------------------------- #
def test_tray_jp_menu_structure_and_signals(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    captured: list[object] = []
    tray.jp_level_selected.connect(lambda v: captured.append(("level", v)))
    tray.jp_duration_selected.connect(lambda v: captured.append(("duration", v)))
    tray.jp_daily_limit_selected.connect(lambda v: captured.append(("limit", v)))
    tray.jp_show_now_requested.connect(lambda: captured.append(("show_now",)))
    tray.jp_vocab_requested.connect(lambda: captured.append(("vocab",)))
    tray.jp_log_requested.connect(lambda: captured.append(("log",)))

    assert set(tray._jp_level_actions) == set(C.JP_LEVELS)
    assert set(tray._jp_duration_actions) == set(C.JP_BUBBLE_DURATION_OPTIONS)
    assert set(tray._jp_daily_limit_actions) == set(C.JP_DAILY_LIMIT_OPTIONS)

    tray._jp_level_actions["N4"].trigger()
    tray._jp_duration_actions[60].trigger()
    tray._jp_daily_limit_actions[20].trigger()
    tray._action_jp_show_now.trigger()
    tray._action_jp_vocab.trigger()
    tray._action_jp_log.trigger()
    assert captured == [
        ("level", "N4"),
        ("duration", 60),
        ("limit", 20),
        ("show_now",),
        ("vocab",),
        ("log",),
    ]


def test_tray_review_limit_menu_structure_and_sync(qtbot) -> None:
    """「复习上限」子菜单：档位集合 / 信号载荷 / 勾选同步 / 关闭学习置灰。"""

    tray = TrayController(QIcon(), AppConfig())
    captured: list[int] = []
    tray.jp_review_limit_selected.connect(captured.append)

    assert set(tray._jp_review_limit_actions) == set(C.JP_REVIEW_DAILY_LIMIT_OPTIONS)

    tray._jp_review_limit_actions[30].trigger()
    assert captured == [30]

    tray.set_jp_review_limit_checked(50)
    assert tray._jp_review_limit_actions[50].isChecked()
    assert not tray._jp_review_limit_actions[30].isChecked()

    tray.set_jp_enabled(False)
    assert not tray._jp_review_limit_menu.isEnabled()
    tray.set_jp_enabled(True)
    assert tray._jp_review_limit_menu.isEnabled()


def test_tray_set_jp_enabled_greys_out(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())

    tray.set_jp_enabled(False)
    assert tray._jp_level_menu.isEnabled() is False
    assert tray._jp_duration_menu.isEnabled() is False
    assert tray._jp_daily_limit_menu.isEnabled() is False
    assert tray._action_jp_show_now.isEnabled() is False  # 立即显示随开关置灰
    assert tray._action_jp_vocab.isEnabled() is True       # 生词本始终可用
    assert tray._action_jp_log.isEnabled() is True         # 学习记录始终可用

    tray.set_jp_enabled(True)
    assert tray._jp_level_menu.isEnabled() is True
    assert tray._jp_duration_menu.isEnabled() is True
    assert tray._jp_daily_limit_menu.isEnabled() is True
    assert tray._action_jp_show_now.isEnabled() is True


def test_tray_set_jp_duration_and_daily_limit_checked(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    tray.set_jp_duration_checked(60)
    assert tray._jp_duration_actions[60].isChecked() is True
    assert tray._jp_duration_actions[30].isChecked() is False

    tray.set_jp_daily_limit_checked(20)
    assert tray._jp_daily_limit_actions[20].isChecked() is True
    assert tray._jp_daily_limit_actions[15].isChecked() is False


def test_tray_set_jp_checked_and_level(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    tray.set_jp_checked(True)
    assert tray._action_jp.isChecked() is True
    tray.set_jp_level_checked("N3")
    assert tray._jp_level_actions["N3"].isChecked() is True
    assert tray._jp_level_actions["N5"].isChecked() is False


# --------------------------------------------------------------------------- #
# 3. 生词本窗口
# --------------------------------------------------------------------------- #
def test_vocab_window_empty_state(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([])
    assert window.level_filter() == C.JP_VOCAB_FILTER_ALL
    assert window._stack.currentWidget() is window._empty_label
    assert window._status.text() == C.JP_VOCAB_STATUS_TEMPLATE.format(count=0)


def test_vocab_window_refresh_orders_newest_first(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([_item(1), _item(2)])
    # 新在后 → 展示反转 → 首张卡片是最后加入的（dict 保持插入序）
    assert list(window._card_by_id.keys()) == ["n5-0002", "n5-0001"]


def test_vocab_window_level_filter(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([_item(1, "N5"), _item(2, "N4")])
    window._tab_buttons["N4"].click()
    assert window.level_filter() == "N4"
    assert list(window._card_by_id.keys()) == ["n4-0002"]


def test_vocab_window_remove_emits_signal(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([_item(1)])
    captured: list[str] = []
    window.remove_requested.connect(captured.append)
    window._on_card_clicked("n5-0001")
    assert window._btn_remove.isEnabled()
    window._btn_remove.click()
    assert captured == ["n5-0001"]


def test_vocab_window_has_title_and_size(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == C.JP_VOCAB_WINDOW_TITLE
    assert window.width() == C.VOCAB_WINDOW_W
    assert window.height() == C.VOCAB_WINDOW_H
