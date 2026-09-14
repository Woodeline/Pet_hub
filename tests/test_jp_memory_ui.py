"""日语记忆 UI + controller 无头冒烟（JP-17+）。

- 按钮条：信号 / 几何 / **不含**点击穿透标志。
- 记录窗口：日期 / 状态筛选 / 统计栏。
- 气泡：``show_word`` 时长解钳 + ``pointing_down`` 访问器冒烟。
- controller：三态单飞 / 超时未处理 / 每日上限 / 全部掌握提前停 / 跨日恢复。

使用 ``qtbot``（``QT_QPA_PLATFORM=offscreen``），**不弹真实窗口**。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker
from desktop_pet.ui.bubble import BubbleWindow
from desktop_pet.ui.bubble_button_bar import BubbleButtonBar
from desktop_pet.ui.log_window import LogWindow


def _entry(i: int = 1, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}",
        kana="かな", translation="译", meaning="义",
    )


def _log_entry(i: int, status: str, day: str = "2025-01-01") -> DailyLogEntry:
    return DailyLogEntry.from_entry(_entry(i), f"{day}T00:00:0{i}Z", status)


# --------------------------------------------------------------------------- #
# 1. 按钮条：信号 / 几何 / 交互属性
# --------------------------------------------------------------------------- #
def test_button_bar_signals(qtbot) -> None:
    bar = BubbleButtonBar()
    qtbot.addWidget(bar)
    captured: list[str] = []
    bar.mastered_clicked.connect(lambda: captured.append("mastered"))
    bar.vocab_clicked.connect(lambda: captured.append("vocab"))

    bar._btn_mastered.click()
    bar._btn_vocab.click()
    assert captured == ["mastered", "vocab"]


def test_button_bar_not_transparent_for_input(qtbot) -> None:
    bar = BubbleButtonBar()
    qtbot.addWidget(bar)

    assert Qt.WindowType.WindowTransparentForInput not in bar.windowFlags()
    assert bar.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is False
    assert bar.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating) is True
    assert bar._btn_mastered.focusPolicy() == Qt.FocusPolicy.NoFocus
    assert bar._btn_vocab.focusPolicy() == Qt.FocusPolicy.NoFocus


def test_button_bar_geometry_below_bubble(qtbot) -> None:
    bar = BubbleButtonBar()
    qtbot.addWidget(bar)
    anchor = QPoint(400, 300)
    bubble_rect = QRect(300, 100, 200, 60)

    geom = bar._compute_geometry(anchor, bubble_rect, pointing_down=True)
    assert geom.top() == bubble_rect.bottom() + C.JP_BUTTON_BAR_GAP_PX
    assert abs(geom.center().x() - anchor.x()) <= 1


def test_button_bar_geometry_above_bubble(qtbot) -> None:
    bar = BubbleButtonBar()
    qtbot.addWidget(bar)
    anchor = QPoint(400, 300)
    bubble_rect = QRect(300, 500, 200, 60)

    geom = bar._compute_geometry(anchor, bubble_rect, pointing_down=False)
    # bar_bottom（下边缘）= bubble_rect.top() - gap
    assert geom.top() + geom.height() == bubble_rect.top() - C.JP_BUTTON_BAR_GAP_PX
    assert abs(geom.center().x() - anchor.x()) <= 1


def test_button_bar_hide_stops_timer(qtbot) -> None:
    bar = BubbleButtonBar()
    qtbot.addWidget(bar)
    bar.show_bar(QPoint(400, 300), QRect(300, 100, 200, 60), True, 30.0)
    assert bar.isVisible()
    bar.hide_bar()
    assert not bar.isVisible()
    assert not bar._timer.isActive()


# --------------------------------------------------------------------------- #
# 2. 记录窗口：日期 / 状态筛选 / 统计
# --------------------------------------------------------------------------- #
def test_log_window_dates_and_current(qtbot) -> None:
    window = LogWindow()
    qtbot.addWidget(window)
    window.set_dates(["2025-01-03", "2025-01-02", "2025-01-01"])
    window.refresh("2025-01-01", [_log_entry(1, C.DAILY_LOG_STATUS_MASTERED)], 15)

    assert window.current_day() == "2025-01-01"
    assert window.current_status() == C.JP_LOG_FILTER_ALL
    assert window._table.rowCount() == 1
    assert window._table.item(0, 0).text() == "語1"


def test_log_window_status_filter(qtbot) -> None:
    window = LogWindow()
    qtbot.addWidget(window)
    entries = [
        _log_entry(1, C.DAILY_LOG_STATUS_MASTERED),
        _log_entry(2, C.DAILY_LOG_STATUS_VOCAB),
        _log_entry(3, C.DAILY_LOG_STATUS_UNPROCESSED),
    ]
    window.refresh("2025-01-01", entries, 15)

    window._combo_status.setCurrentIndex(
        window._combo_status.findData(C.DAILY_LOG_STATUS_MASTERED)
    )
    assert window.current_status() == C.DAILY_LOG_STATUS_MASTERED
    assert window._table.rowCount() == 1
    assert window._table.item(0, 0).text() == "語1"

    window._combo_status.setCurrentIndex(
        window._combo_status.findData(C.DAILY_LOG_STATUS_UNPROCESSED)
    )
    assert window._table.rowCount() == 1
    assert window._table.item(0, 0).text() == "語3"


def test_log_window_statistics_are_unfiltered(qtbot) -> None:
    window = LogWindow()
    qtbot.addWidget(window)
    entries = [
        _log_entry(1, C.DAILY_LOG_STATUS_MASTERED),
        _log_entry(2, C.DAILY_LOG_STATUS_MASTERED),
        _log_entry(3, C.DAILY_LOG_STATUS_VOCAB),
        _log_entry(4, C.DAILY_LOG_STATUS_UNPROCESSED),
    ]
    window.refresh("2025-01-01", entries, 15)

    expected = C.JP_LOG_STATUS_TEMPLATE.format(
        shown=4, limit=15, mastered=2, vocab=1, unprocessed=1
    )
    assert window._status_label.text() == expected


def test_log_window_switch_day_locally(qtbot) -> None:
    window = LogWindow()
    qtbot.addWidget(window)
    window.refresh("2025-01-01", [_log_entry(1, C.DAILY_LOG_STATUS_MASTERED)], 15)
    window.refresh("2025-01-02", [_log_entry(2, C.DAILY_LOG_STATUS_VOCAB)], 15)

    window._combo_date.setCurrentIndex(window._combo_date.findData("2025-01-01"))
    assert window.current_day() == "2025-01-01"
    assert window._table.rowCount() == 1
    assert window._table.item(0, 0).text() == "語1"


def test_log_window_title_and_size(qtbot) -> None:
    window = LogWindow()
    qtbot.addWidget(window)
    assert window.windowTitle() == C.JP_LOG_WINDOW_TITLE
    assert window.width() == C.JP_LOG_WINDOW_W
    assert window.height() == C.JP_LOG_WINDOW_H


# --------------------------------------------------------------------------- #
# 3. 气泡：时长解钳 + pointing_down 访问器
# --------------------------------------------------------------------------- #
def test_show_word_duration_unclamped(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)
    assert bubble._duration == 30.0  # 不再被钳到 4

    bubble.show_word(_entry(), 9999.0)
    assert bubble._duration == C.JP_BUBBLE_MAX_DURATION_S
    bubble.show_word(_entry(), 0.1)
    assert bubble._duration == C.JP_BUBBLE_MIN_DURATION_S
    bubble.hide_bubble()


def test_bubble_pointing_down_accessor(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    assert bubble.pointing_down() is True
    bubble._pointing_down = False
    assert bubble.pointing_down() is False


# --------------------------------------------------------------------------- #
# 4. controller 级无头冒烟（三态单飞 / 上限 / 提前停 / 跨日）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """构造最小 controller（store 全部指向 tmp_path，注入 3 词小词库）。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.jp_enabled = True
    ctrl._cfg.bubble_enabled = True
    ctrl._cfg.jp_level = "N5"
    ctrl._cfg.jp_daily_limit = 5
    ctrl._cfg.jp_bubble_duration_s = 30.0

    entries = tuple(_entry(i) for i in range(1, 4))
    ctrl._bank = WordBank(entries)
    ctrl._picker = WeightedWordPicker(ctrl._bank, random.Random(0))

    ctrl._mastered = MasteredStore(tmp_path / "mastered.json")
    ctrl._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    ctrl._vocab = VocabStore(tmp_path / "vocab.json")
    ctrl._mastered.load()
    ctrl._daily_log.load()
    ctrl._vocab.load()

    ctrl._today_str = "2025-01-01"
    ctrl._last_bubble_ts = float("-inf")
    return ctrl


def test_controller_show_and_mastered_single_fly(controller: PetAppController) -> None:
    controller._show_word_bubble(0.0)
    assert controller._current_word is not None
    assert controller._word_disposed is False

    # 第一次处置：已掌握
    controller._dispose_word(C.DAILY_LOG_STATUS_MASTERED, 1.0)
    assert controller._current_word is None
    assert controller._mastered.count() == 1
    assert controller._daily_log.mastered_count_for("2025-01-01") == 1

    # 第二次处置：单飞 no-op
    controller._dispose_word(C.DAILY_LOG_STATUS_MASTERED, 2.0)
    assert controller._mastered.count() == 1
    assert controller._daily_log.count_for("2025-01-01") == 1


def test_controller_timeout_records_unprocessed(controller: PetAppController) -> None:
    controller._show_word_bubble(0.0)
    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 30.0)
    assert controller._mastered.count() == 0
    assert controller._daily_log.unprocessed_count_for("2025-01-01") == 1
    assert controller._current_word is None


def test_controller_race_only_one_terminal_state(controller: PetAppController) -> None:
    """超时先落「未处理」→ 随后点击被单飞丢弃，一次展示只落一种终态。"""

    controller._show_word_bubble(0.0)
    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 30.0)  # 超时先执行
    controller._dispose_word(C.DAILY_LOG_STATUS_MASTERED, 30.1)     # 迟到点击
    assert controller._daily_log.count_for("2025-01-01") == 1
    assert controller._daily_log.unprocessed_count_for("2025-01-01") == 1
    assert controller._mastered.count() == 0


def test_controller_daily_limit_stops(controller: PetAppController) -> None:
    for i in range(1, 6):  # limit = 5
        controller._daily_log.add_entry(
            "2025-01-01", _log_entry(i, C.DAILY_LOG_STATUS_UNPROCESSED)
        )
    assert controller._jp_stop_for_today() is True
    controller._show_word_bubble(0.0)
    assert controller._current_word is None  # 达上限不再展示


def test_controller_all_mastered_stops_early(controller: PetAppController) -> None:
    controller._daily_log.add_entry("2025-01-01", _log_entry(1, C.DAILY_LOG_STATUS_MASTERED))
    controller._daily_log.add_entry("2025-01-01", _log_entry(2, C.DAILY_LOG_STATUS_MASTERED))
    assert controller._jp_stop_for_today() is True


def test_controller_cross_day_resets(controller: PetAppController, monkeypatch) -> None:
    controller._cfg.jp_enabled = False  # 隔离跨日分支，避免到点展示覆盖 _next_word_ts
    controller._today_str = "2025-01-01"
    controller._today_done_notified = True
    controller._next_word_ts = float("inf")
    monkeypatch.setattr(controller, "_local_date_str", lambda: "2025-01-02")

    controller._on_frame_tick(100.0)

    assert controller._today_str == "2025-01-02"
    assert controller._today_done_notified is False
    assert controller._next_word_ts == 100.0


def test_controller_local_date_str_format(controller: PetAppController) -> None:
    value = controller._local_date_str()
    import re

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), f"非法日期 key：{value}"
