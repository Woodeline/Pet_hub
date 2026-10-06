"""工程师自测：core.weak_words —— 错题本（易错词）派生纯逻辑。

覆盖：
1. 聚合：按 id 跨天累计 review_lapsed；非 review_lapsed 状态不计。
2. 阈值：遗忘次数 < ``WEAK_WORD_MIN_LAPSES`` 不入选；同日多次逐次计。
3. 排序：次数降序为主、最近遗忘降序为次；``limit`` 截断。
4. 快照字段：word/kana/translation/level 来自最后一次 lapsed 快照。

core 零时钟约定：shown_at 为注入的 ISO 字符串，仅做字典序比较。
"""

from __future__ import annotations

from pathlib import Path

from desktop_pet.core import constants as C
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.weak_words import WeakWord, collect_weak_words

_DAYS: tuple[str, ...] = tuple(f"2025-01-0{i}" for i in range(1, 6))


def _entry(word_id: int, status: str, day: str, shown_seq: int = 0) -> DailyLogEntry:
    """构造一条每日记录（``shown_seq`` 保证同日多条记录时间有序）。"""

    return DailyLogEntry(
        id=f"n5-{word_id:04d}",
        level="N5",
        word=f"語{word_id}",
        kana=f"かな{word_id}",
        translation=f"译{word_id}",
        shown_at=f"{day}T00:00:{shown_seq:02d}Z",
        status=status,
    )


def _store(tmp_path: Path, entries: list[tuple[str, DailyLogEntry]]) -> DailyLogStore:
    store = DailyLogStore(tmp_path / "daily_log.json")
    store.load()
    for day, entry in entries:
        store.add_entry(day, entry)
    return store


def test_no_lapses_returns_empty(tmp_path: Path) -> None:
    """没有任何 review_lapsed：返回空元组。"""

    entries = [(_DAYS[0], _entry(1, "review_ok", _DAYS[0]))]
    assert collect_weak_words(_store(tmp_path, entries)) == ()


def test_single_lapse_below_threshold_excluded(tmp_path: Path) -> None:
    """只忘过 1 次：正常记忆波动，不进错题本。"""

    entries = [(_DAYS[0], _entry(1, "review_lapsed", _DAYS[0]))]
    assert collect_weak_words(_store(tmp_path, entries)) == ()


def test_aggregates_across_days_and_counts_each_lapse(tmp_path: Path) -> None:
    """跨天 + 同日多次：逐次累计（2 + 1 = 3 次）。"""

    entries = [
        (_DAYS[0], _entry(1, "review_lapsed", _DAYS[0])),
        (_DAYS[1], _entry(1, "review_lapsed", _DAYS[1])),
        (_DAYS[2], _entry(1, "review_lapsed", _DAYS[2], shown_seq=1)),
        (_DAYS[2], _entry(1, "review_lapsed", _DAYS[2], shown_seq=2)),
    ]
    weak = collect_weak_words(_store(tmp_path, entries))
    assert len(weak) == 1
    assert weak[0].id == "n5-0001"
    assert weak[0].lapsed_count == 4


def test_mixed_statuses_only_lapsed_counted(tmp_path: Path) -> None:
    """忘了 → 重新掌握 → 又忘了：只有 lapsed 计数（ok/unprocessed 不计）。"""

    entries = [
        (_DAYS[0], _entry(1, "review_lapsed", _DAYS[0])),
        (_DAYS[1], _entry(1, "review_ok", _DAYS[1])),
        (_DAYS[2], _entry(1, "unprocessed", _DAYS[2])),
        (_DAYS[3], _entry(1, "review_lapsed", _DAYS[3])),
    ]
    weak = collect_weak_words(_store(tmp_path, entries))
    assert len(weak) == 1
    assert weak[0].lapsed_count == 2


def test_sort_count_desc_then_recency(tmp_path: Path) -> None:
    """主键次数降序；次数相同时最近遗忘的排前。"""

    entries = [
        # 語1：忘 2 次（较早）
        (_DAYS[0], _entry(1, "review_lapsed", _DAYS[0])),
        (_DAYS[1], _entry(1, "review_lapsed", _DAYS[1])),
        # 語2：忘 3 次（最多，排最前）
        (_DAYS[0], _entry(2, "review_lapsed", _DAYS[0])),
        (_DAYS[2], _entry(2, "review_lapsed", _DAYS[2])),
        (_DAYS[3], _entry(2, "review_lapsed", _DAYS[3])),
        # 語3：忘 2 次（最晚，排在語1 前）
        (_DAYS[4], _entry(3, "review_lapsed", _DAYS[4])),
        (_DAYS[3], _entry(3, "review_lapsed", _DAYS[3])),
    ]
    weak = collect_weak_words(_store(tmp_path, entries))
    assert [w.id for w in weak] == ["n5-0002", "n5-0003", "n5-0001"]


def test_limit_truncates(tmp_path: Path) -> None:
    """limit 截断（TopN 上限）；limit<=0 返回空。"""

    entries = [
        (day, _entry(word_id, "review_lapsed", day))
        for word_id in range(1, 4)
        for day in (_DAYS[0], _DAYS[1])
    ]
    store = _store(tmp_path, entries)
    assert len(collect_weak_words(store)) == 3
    assert len(collect_weak_words(store, limit=2)) == 2
    assert collect_weak_words(store, limit=0) == ()


def test_snapshot_fields_from_last_lapse(tmp_path: Path) -> None:
    """快照字段取自 lapsed 记录本身（word/kana/translation/level、最近时间）。"""

    entries = [
        (_DAYS[0], _entry(1, "review_lapsed", _DAYS[0])),
        (_DAYS[2], _entry(1, "review_lapsed", _DAYS[2])),
    ]
    weak = collect_weak_words(_store(tmp_path, entries))
    assert weak[0].level == "N5"
    assert weak[0].word == "語1"
    assert weak[0].kana == "かな1"
    assert weak[0].translation == "译1"
    assert weak[0].last_lapsed_at == f"{_DAYS[2]}T00:00:00Z"


def test_constants_match_prd() -> None:
    """错题本常量与设计一致（防漂移）。"""

    assert C.WEAK_WORD_MIN_LAPSES == 2
    assert C.WEAK_WORD_BOOST == 2.0
    assert C.WEAK_WORD_TOP_N == 10
