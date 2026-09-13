"""日语学习 UI 冒烟（气泡多行渲染 / 托盘菜单 / 生词本窗口）。

使用 ``qtbot``（``conftest.py`` 已设 ``QT_QPA_PLATFORM=offscreen``），**不弹真实窗口**。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
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

    expected_w = int(round(C.JP_BUBBLE_MAX_WIDTH + C.BUBBLE_PAD_X * 2.0))
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
# 1.5 学习泡泡交互按钮（JP-17）
# --------------------------------------------------------------------------- #
def test_show_word_shows_buttons_and_interactive(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)

    assert bubble._btn_learned.isVisible()
    assert bubble._btn_new.isVisible()
    assert bubble._btn_learned.text() == C.JP_BTN_LEARNED
    assert bubble._btn_new.text() == C.JP_BTN_NEW_WORD
    # 单词模式窗口接收鼠标（非点击穿透）
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is False

    # 按钮位于泡泡主体底部区域内
    for btn in (bubble._btn_learned, bubble._btn_new):
        assert btn.y() + btn.height() <= bubble.height()
        assert btn.x() >= 0 and btn.x() + btn.width() <= bubble.width()
    bubble.hide_bubble()


def test_word_button_clicks_emit_signals_and_hide(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)

    captured: list[str] = []
    bubble.learned_clicked.connect(lambda: captured.append("learned"))
    bubble.new_word_clicked.connect(lambda: captured.append("new"))

    bubble._btn_learned.click()
    assert captured == ["learned"]
    assert not bubble.isVisible(), "点击后气泡未隐藏"
    assert not bubble._btn_learned.isVisible()

    bubble.show_word(_entry(), 30.0)
    bubble._btn_new.click()
    assert captured == ["learned", "new"]
    assert not bubble.isVisible()


def test_show_message_hides_buttons_and_restores_passthru(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)
    bubble.show_message("你好呀~", 2.0)

    assert not bubble._btn_learned.isVisible()
    assert not bubble._btn_new.isVisible()
    # 文本模式恢复完全点击穿透
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is True
    bubble.hide_bubble()


def test_word_duration_clamped_to_configurable_range(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))

    bubble.show_word(_entry(), 0.5)   # 低于下限 → 钳到 5
    assert bubble._duration == C.JP_BUBBLE_DURATION_MIN_S
    bubble.show_word(_entry(), 9999)  # 高于上限 → 钳到 120
    assert bubble._duration == C.JP_BUBBLE_DURATION_MAX_S
    bubble.show_word(_entry(), 30.0)
    assert bubble._duration == 30.0
    bubble.hide_bubble()


# --------------------------------------------------------------------------- #
# 2. 托盘日语菜单
# --------------------------------------------------------------------------- #
def test_tray_jp_menu_structure_and_signals(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    captured: list[str] = []
    tray.jp_level_selected.connect(captured.append)
    tray.jp_remember_requested.connect(lambda: captured.append("remember"))
    tray.jp_vocab_requested.connect(lambda: captured.append("vocab"))

    assert set(tray._jp_level_actions) == set(C.JP_LEVELS)
    tray._jp_level_actions["N4"].trigger()
    tray._action_jp_remember.trigger()
    tray._action_jp_vocab.trigger()
    assert captured == ["N4", "remember", "vocab"]


def test_tray_set_jp_enabled_greys_out(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())

    tray.set_jp_enabled(False)
    assert tray._jp_level_menu.isEnabled() is False
    assert tray._action_jp_remember.isEnabled() is False
    assert tray._action_jp_vocab.isEnabled() is True  # 生词本始终可用

    tray.set_jp_enabled(True)
    assert tray._jp_level_menu.isEnabled() is True
    assert tray._action_jp_remember.isEnabled() is True


def test_tray_current_word_label(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    tray.set_jp_current_word("私")
    assert tray._action_jp_remember.text() == C.JP_MENU_REMEMBER_TEMPLATE.format(word="私")
    tray.set_jp_current_word(None)
    assert tray._action_jp_remember.text() == C.JP_MENU_REMEMBER


def test_tray_set_jp_checked_and_level(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    tray.set_jp_checked(True)
    assert tray._action_jp.isChecked() is True
    tray.set_jp_level_checked("N3")
    assert tray._jp_level_actions["N3"].isChecked() is True
    assert tray._jp_level_actions["N5"].isChecked() is False


# --------------------------------------------------------------------------- #
# 2.5 托盘可调参数菜单（JP-17/18）
# --------------------------------------------------------------------------- #
def test_tray_duration_and_daily_menus_structure_and_signals(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    captured: list = []
    tray.jp_duration_selected.connect(captured.append)
    tray.jp_daily_selected.connect(captured.append)

    assert set(tray._jp_duration_actions) == set(C.JP_DURATION_CHOICES_S)
    assert set(tray._jp_daily_actions) == set(C.JP_DAILY_CHOICES)
    # 默认配置勾选档位
    assert tray._jp_duration_actions[30.0].isChecked() is True
    assert tray._jp_daily_actions[15].isChecked() is True

    tray._jp_duration_actions[60.0].trigger()
    tray._jp_daily_actions[20].trigger()
    assert captured == [60.0, 20]


def test_tray_duration_daily_checked_sync(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    tray.set_jp_duration_checked(120.0)
    assert tray._jp_duration_actions[120.0].isChecked() is True
    assert tray._jp_duration_actions[30.0].isChecked() is False
    tray.set_jp_daily_checked(5)
    assert tray._jp_daily_actions[5].isChecked() is True
    assert tray._jp_daily_actions[15].isChecked() is False


def test_tray_jp_disabled_greys_duration_and_daily(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    tray.set_jp_enabled(False)
    assert tray._jp_duration_menu.isEnabled() is False
    assert tray._jp_daily_menu.isEnabled() is False
    tray.set_jp_enabled(True)
    assert tray._jp_duration_menu.isEnabled() is True
    assert tray._jp_daily_menu.isEnabled() is True


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
    assert window._table.rowCount() == 2
    # 新在后 → 展示反转 → 首行是最后加入的
    assert window._table.item(0, 0).text() == "語2"


def test_vocab_window_level_filter(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([_item(1, "N5"), _item(2, "N4")])
    window._combo.setCurrentIndex(window._combo.findData("N4"))
    assert window.level_filter() == "N4"
    assert window._table.rowCount() == 1
    assert window._table.item(0, 3).text() == "N4"


def test_vocab_window_remove_emits_signal(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([_item(1)])
    captured: list[str] = []
    window.remove_requested.connect(captured.append)
    window._table.selectRow(0)
    assert window._btn_remove.isEnabled()
    window._btn_remove.click()
    assert captured == ["n5-0001"]


def test_vocab_window_has_title_and_size(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == C.JP_VOCAB_WINDOW_TITLE
    assert window.width() == C.VOCAB_WINDOW_W
    assert window.height() == C.VOCAB_WINDOW_H
