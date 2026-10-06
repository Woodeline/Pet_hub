"""工程师自测：ui.stats_window —— 学习统计窗口（offscreen 构建与刷新）。

覆盖：
1. 色阶档位函数边界（0 / 阈值内 / 阈值上 / 溢出）。
2. refresh 喂数：概览四块数值正确、空态提示可见性切换。
3. 渲染冒烟：含热力图与曲线的整窗 grab 不崩溃、非空。

窗口为纯展示层：不读写存储，断言仅针对 UI 状态。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt

from desktop_pet.core import constants as C
from desktop_pet.core.stats_aggregator import StatsSummary
from desktop_pet.core.weak_words import WeakWord
from desktop_pet.ui.stats_window import StatsWindow, _level_for


def _summary(
    *,
    days: tuple[str, ...] = ("2025-01-01", "2025-01-02", "2025-01-03"),
    new_words: dict[str, int] | None = None,
    review_ok: dict[str, int] | None = None,
    review_lapsed: dict[str, int] | None = None,
    streak: int = 0,
    curve: tuple[tuple[str, int], ...] | None = None,
) -> StatsSummary:
    """构造最小 StatsSummary（未提供的桶全零）。"""

    new_words = new_words if new_words is not None else {day: 0 for day in days}
    review_ok = review_ok if review_ok is not None else {day: 0 for day in days}
    review_lapsed = review_lapsed if review_lapsed is not None else {day: 0 for day in days}
    return StatsSummary(
        day_keys=days,
        new_words=new_words,
        review_ok=review_ok,
        review_lapsed=review_lapsed,
        streak_days=streak,
        mastered_curve=curve if curve is not None else tuple((day, 0) for day in days),
        total_mastered=curve[-1][1] if curve else 0,
    )


# --------------------------------------------------------------------------- #
# 色阶档位
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "count,expected",
    [
        (0, 0),
        (1, 1),
        (C.STATS_HEATMAP_LEVEL1_MAX, 1),
        (C.STATS_HEATMAP_LEVEL1_MAX + 1, 2),
        (C.STATS_HEATMAP_LEVEL2_MAX, 2),
        (C.STATS_HEATMAP_LEVEL2_MAX + 1, 3),
    ],
)
def test_level_for_thresholds(count: int, expected: int) -> None:
    """色阶阈值与常量联动（0 档空格 / 1..L1 浅 / ..L2 中 / 其余浓）。"""

    assert _level_for(count) == expected


# --------------------------------------------------------------------------- #
# refresh 喂数
# --------------------------------------------------------------------------- #
def test_refresh_updates_overview_blocks(qtbot) -> None:
    """概览四块：打卡 / 累计掌握 / 今日新词 / 今日复习 数值正确。"""

    window = StatsWindow()
    qtbot.addWidget(window)
    days = ("2025-01-02", "2025-01-03")
    summary = _summary(
        days=days,
        new_words={days[0]: 3, days[1]: 5},
        review_ok={days[0]: 0, days[1]: 2},
        review_lapsed={days[0]: 0, days[1]: 1},
        streak=4,
        curve=((days[0], 10), (days[1], 15)),
    )
    window.refresh(summary, 15, 20)

    assert window._streak_block._value_label.text() == f"4 {C.STATS_STREAK_UNIT}"
    assert window._mastered_block._value_label.text() == f"15 {C.STATS_MASTERED_UNIT}"
    # 今日（末位）新词 5/15、复习 3/20
    assert window._today_new_block._value_label.text() == "5 / 15"
    assert window._today_review_block._value_label.text() == "3 / 20"


def test_refresh_toggles_empty_hint(qtbot) -> None:
    """全零数据 → 空态提示可见；有记录 → 隐藏。"""

    window = StatsWindow()
    qtbot.addWidget(window)
    window.refresh(_summary(), 15, 20)
    assert window._empty_hint.isVisibleTo(window)

    days = ("2025-01-02", "2025-01-03")
    summary = _summary(
        days=days,
        new_words={days[0]: 1, days[1]: 0},
        curve=((days[0], 0), (days[1], 1)),
    )
    window.refresh(summary, 15, 20)
    assert not window._empty_hint.isVisibleTo(window)


# --------------------------------------------------------------------------- #
# 渲染冒烟
# --------------------------------------------------------------------------- #
def test_paint_smoke_heatmap_and_curve(qtbot) -> None:
    """含数据与空数据两种状态下整窗 grab 均不崩溃且非空。"""

    window = StatsWindow()
    qtbot.addWidget(window)
    window.resize(C.JP_STATS_WINDOW_W, C.JP_STATS_WINDOW_H)

    window.refresh(_summary(), 15, 20)
    assert not window.grab().isNull()

    days = ("2025-01-02", "2025-01-03")
    summary = _summary(
        days=days,
        new_words={days[0]: 2, days[1]: 7},
        review_ok={days[0]: 1, days[1]: 0},
        curve=((days[0], 3), (days[1], 8)),
    )
    window.refresh(summary, 15, 20)
    assert not window.grab().isNull()


# --------------------------------------------------------------------------- #
# 易错词区块（批次 2）
# --------------------------------------------------------------------------- #
def _weak(word_id: str, count: int) -> WeakWord:
    return WeakWord(
        id=word_id,
        level="N5",
        word=f"語{word_id}",
        kana="かな",
        translation="译",
        lapsed_count=count,
        last_lapsed_at="2025-01-01T00:00:00Z",
    )


def _weak_row_widgets(window: StatsWindow) -> list:
    return [
        window._weak_rows.itemAt(i).widget()
        for i in range(window._weak_rows.count())
        if window._weak_rows.itemAt(i).widget() is not None
    ]


def test_weak_section_empty_shows_hint(qtbot) -> None:
    """无易错词：空态提示可见、无双击提示。"""

    window = StatsWindow()
    qtbot.addWidget(window)
    window.set_weak_words(())
    assert window._weak_empty.isVisibleTo(window)
    assert not window._weak_hint.isVisibleTo(window)
    assert _weak_row_widgets(window) == []


def test_weak_section_rows_and_double_click(qtbot) -> None:
    """有易错词：行按序重建；双击行发出携带 id 的详情信号。"""

    window = StatsWindow()
    qtbot.addWidget(window)
    window.set_weak_words((_weak("n5-0001", 2), _weak("n5-0002", 3)))
    assert not window._weak_empty.isVisibleTo(window)
    assert window._weak_hint.isVisibleTo(window)
    rows = _weak_row_widgets(window)
    assert len(rows) == 2

    with qtbot.waitSignal(window.weak_word_double_clicked, timeout=2000) as blocker:
        qtbot.mouseDClick(rows[1], Qt.MouseButton.LeftButton)
    assert blocker.args == ["n5-0002"]


def test_weak_section_rebuild_replaces_rows(qtbot) -> None:
    """再次喂数：旧行被清除，不残留。"""

    window = StatsWindow()
    qtbot.addWidget(window)
    window.set_weak_words((_weak("n5-0001", 2), _weak("n5-0002", 3)))
    window.set_weak_words((_weak("n5-0009", 5),))
    rows = _weak_row_widgets(window)
    assert len(rows) == 1
