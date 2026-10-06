"""工程师自测：core.stats_aggregator —— 统计聚合纯逻辑（打卡 / 分桶 / 曲线）。

覆盖：
1. 空数据：全零、streak=0、曲线全零。
2. 连续打卡：含今天 / 今天未学不断签 / 中间断签清零 / 全空。
3. 状态分桶：新词三态计入 new_words，复习两态各自独立。
4. 掌握曲线：窗口前存量计入起点、窗口内逐日累加、窗口外（未来日期）不计。

core 零时钟约定：日期 key 全部由测试显式注入，模块自身绝不解析日期。
"""

from __future__ import annotations

from pathlib import Path

from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.mastered_store import MasteredItem
from desktop_pet.core.stats_aggregator import build_summary, count_streak

_DAYS: tuple[str, ...] = tuple(f"2025-01-0{i}" for i in range(1, 6))  # 01~05 升序


def _log_entry(word_id: int, status: str, day: str) -> DailyLogEntry:
    """构造一条每日记录（id 唯一即可，字段为最小合法快照）。"""

    return DailyLogEntry(
        id=f"n5-{word_id:04d}",
        level="N5",
        word=f"語{word_id}",
        kana="かな",
        translation="译",
        shown_at=f"{day}T00:00:00Z",
        status=status,
    )


def _seed_log(tmp_path: Path, entries: list[tuple[str, DailyLogEntry]]) -> DailyLogStore:
    """按 ``(day, entry)`` 列表种入每日记录（走 add_entry 正常落盘路径）。"""

    store = DailyLogStore(tmp_path / "daily_log.json")
    store.load()
    for day, entry in entries:
        store.add_entry(day, entry)
    return store


def _mastered(word_id: int, mastered_at: str) -> MasteredItem:
    return MasteredItem(
        id=f"n5-{word_id:04d}",
        level="N5",
        word=f"語{word_id}",
        kana="かな",
        translation="译",
        mastered_at=mastered_at,
    )


# --------------------------------------------------------------------------- #
# 空数据
# --------------------------------------------------------------------------- #
def test_empty_summary_all_zero(tmp_path: Path) -> None:
    """无任何记录：全零、无打卡、曲线为全零平线。"""

    store = _seed_log(tmp_path, [])
    summary = build_summary(store, [], _DAYS)

    assert summary.day_keys == _DAYS
    assert summary.streak_days == 0
    assert summary.total_mastered == 0
    assert all(v == 0 for v in summary.new_words.values())
    assert all(v == 0 for v in summary.review_ok.values())
    assert all(v == 0 for v in summary.review_lapsed.values())
    assert summary.mastered_curve == tuple((day, 0) for day in _DAYS)


# --------------------------------------------------------------------------- #
# 连续打卡
# --------------------------------------------------------------------------- #
def test_streak_includes_today_when_active(tmp_path: Path) -> None:
    """今天有记录：连胜包含今天（d4、d5 连续 → 2 天）。"""

    entries = [
        (_DAYS[3], _log_entry(1, "vocab", _DAYS[3])),
        (_DAYS[4], _log_entry(2, "vocab", _DAYS[4])),
    ]
    store = _seed_log(tmp_path, entries)
    assert count_streak(store, _DAYS) == 2


def test_streak_today_empty_keeps_yesterday_chain(tmp_path: Path) -> None:
    """今天（末位）暂无记录不断签：从昨天继续往前数（d3、d4 → 2 天）。"""

    entries = [
        (_DAYS[2], _log_entry(1, "vocab", _DAYS[2])),
        (_DAYS[3], _log_entry(2, "vocab", _DAYS[3])),
    ]
    store = _seed_log(tmp_path, entries)
    assert count_streak(store, _DAYS) == 2


def test_streak_breaks_on_gap(tmp_path: Path) -> None:
    """中间断签（d3 空）清零：d2 再早也只算 d4、d5 的 2 天。"""

    entries = [
        (_DAYS[1], _log_entry(1, "vocab", _DAYS[1])),
        (_DAYS[3], _log_entry(2, "vocab", _DAYS[3])),
        (_DAYS[4], _log_entry(3, "vocab", _DAYS[4])),
    ]
    store = _seed_log(tmp_path, entries)
    assert count_streak(store, _DAYS) == 2


def test_streak_empty_keys() -> None:
    """空日期序列：返回 0（不访问 store 也应安全）。"""

    store = DailyLogStore(Path("unused.json"))
    assert count_streak(store, []) == 0


# --------------------------------------------------------------------------- #
# 状态分桶
# --------------------------------------------------------------------------- #
def test_status_buckets_split_new_words_and_reviews(tmp_path: Path) -> None:
    """新词三态（mastered/vocab/unprocessed）计入新词数；复习两态各自独立。"""

    day = _DAYS[0]
    entries = [
        (day, _log_entry(1, "mastered", day)),
        (day, _log_entry(2, "vocab", day)),
        (day, _log_entry(3, "unprocessed", day)),
        (day, _log_entry(4, "review_ok", day)),
        (day, _log_entry(5, "review_ok", day)),
        (day, _log_entry(6, "review_lapsed", day)),
    ]
    store = _seed_log(tmp_path, entries)
    summary = build_summary(store, [], _DAYS)

    assert summary.new_words[day] == 3
    assert summary.review_ok[day] == 2
    assert summary.review_lapsed[day] == 1


# --------------------------------------------------------------------------- #
# 掌握曲线
# --------------------------------------------------------------------------- #
def test_curve_includes_history_before_window(tmp_path: Path) -> None:
    """窗口前已掌握的词计入曲线起点（存量不从零开始）。"""

    store = _seed_log(tmp_path, [])
    items = [_mastered(1, "2024-12-01T00:00:00Z"), _mastered(2, "2024-12-20T00:00:00Z")]
    summary = build_summary(store, items, _DAYS)

    assert summary.mastered_curve[0] == (_DAYS[0], 2)
    assert summary.total_mastered == 2


def test_curve_increments_mid_window(tmp_path: Path) -> None:
    """窗口内逐日累加：d2 掌握 1 词 → d1 为 0、d2 起为 1。"""

    store = _seed_log(tmp_path, [])
    items = [_mastered(1, f"{_DAYS[1]}T12:00:00Z")]
    summary = build_summary(store, items, _DAYS)

    assert summary.mastered_curve[0] == (_DAYS[0], 0)
    assert summary.mastered_curve[1] == (_DAYS[1], 1)
    assert summary.mastered_curve[-1] == (_DAYS[-1], 1)
    assert summary.total_mastered == 1


def test_curve_ignores_future_mastered_at(tmp_path: Path) -> None:
    """mastered_at 晚于窗口末日（时钟异常）不计入曲线，总数以曲线末值为准。"""

    store = _seed_log(tmp_path, [])
    items = [_mastered(1, f"{_DAYS[1]}T12:00:00Z"), _mastered(2, "2030-01-01T00:00:00Z")]
    summary = build_summary(store, items, _DAYS)

    assert summary.total_mastered == 1


def test_empty_day_keys_curve() -> None:
    """空日期窗口：曲线为空、总数 0。"""

    store = DailyLogStore(Path("unused.json"))
    summary = build_summary(store, [_mastered(1, "2025-01-01T00:00:00Z")], [])

    assert summary.mastered_curve == ()
    assert summary.total_mastered == 0
