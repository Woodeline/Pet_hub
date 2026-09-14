"""每日学习记录持久化 单测（JP-17+）：分桶 / 统计 / 状态校验 / 损坏备份。

全部为 ``core`` 纯逻辑测试，**不需要 Qt**。``day`` 是注入的字符串 key，core 不解析日期。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.vocabulary import VocabEntry


def _entry(i: int, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}",
        kana="かな", translation="译", meaning="义",
    )


def _log(i: int, status: str, day: str = "2025-01-01") -> DailyLogEntry:
    return DailyLogEntry.from_entry(_entry(i), f"{day}T00:00:0{i}Z", status)


@pytest.fixture()
def store(tmp_path: Path) -> DailyLogStore:
    return DailyLogStore(tmp_path / "desktop-pet" / "daily_log.json")


# --------------------------------------------------------------------------- #
# 1. 默认路径
# --------------------------------------------------------------------------- #
def test_default_path_uses_appdata(isolated_appdata: Path) -> None:
    path = DailyLogStore.default_path()
    assert path == isolated_appdata / C.CONFIG_DIR_NAME / C.DAILY_LOG_FILE_NAME


def test_default_path_without_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    path = DailyLogStore.default_path()
    assert path.name == C.DAILY_LOG_FILE_NAME
    assert Path.home() in path.parents


# --------------------------------------------------------------------------- #
# 2. 分桶 / 查询 / 统计
# --------------------------------------------------------------------------- #
def test_load_missing_file_returns_empty(store: DailyLogStore) -> None:
    assert store.load() == {}
    assert store.days() == []
    assert store.count_for("2025-01-01") == 0


def test_add_entry_buckets_by_day(store: DailyLogStore) -> None:
    store.add_entry("2025-01-02", _log(2, C.DAILY_LOG_STATUS_MASTERED))
    store.add_entry("2025-01-01", _log(1, C.DAILY_LOG_STATUS_VOCAB))

    assert store.days() == ["2025-01-02", "2025-01-01"]  # 降序（最新在前）
    assert [e.id for e in store.entries_for("2025-01-01")] == ["n5-0001"]
    assert store.count_for("2025-01-01") == 1
    assert store.count_for("2025-01-02") == 1
    assert store.count_for("2025-01-03") == 0


def test_status_counts_and_shown_ids(store: DailyLogStore) -> None:
    store.add_entry("2025-01-01", _log(1, C.DAILY_LOG_STATUS_MASTERED))
    store.add_entry("2025-01-01", _log(2, C.DAILY_LOG_STATUS_MASTERED))
    store.add_entry("2025-01-01", _log(3, C.DAILY_LOG_STATUS_VOCAB))
    store.add_entry("2025-01-01", _log(4, C.DAILY_LOG_STATUS_UNPROCESSED))

    assert store.mastered_count_for("2025-01-01") == 2
    assert store.vocab_count_for("2025-01-01") == 1
    assert store.unprocessed_count_for("2025-01-01") == 1
    assert store.shown_ids_for("2025-01-01") == {"n5-0001", "n5-0002", "n5-0003", "n5-0004"}


def test_all_mastered_semantics(store: DailyLogStore) -> None:
    # 空桶：shown == 0 → False
    assert store.all_mastered("2025-01-01") is False

    store.add_entry("2025-01-01", _log(1, C.DAILY_LOG_STATUS_MASTERED))
    store.add_entry("2025-01-01", _log(2, C.DAILY_LOG_STATUS_MASTERED))
    assert store.all_mastered("2025-01-01") is True  # shown>0 且 mastered==shown

    store.add_entry("2025-01-01", _log(3, C.DAILY_LOG_STATUS_UNPROCESSED))
    assert store.all_mastered("2025-01-01") is False  # 有未处理 → 不满足


def test_add_entry_persists_to_disk(store: DailyLogStore) -> None:
    store.add_entry("2025-01-01", _log(1, C.DAILY_LOG_STATUS_MASTERED))
    reloaded = DailyLogStore(store.path)
    reloaded.load()
    assert reloaded.count_for("2025-01-01") == 1
    assert reloaded.entries_for("2025-01-01")[0].word == "語1"


def test_add_none_is_noop(store: DailyLogStore) -> None:
    store.add_entry("2025-01-01", None)  # type: ignore[arg-type]
    assert store.count_for("2025-01-01") == 0


# --------------------------------------------------------------------------- #
# 3. DailyLogEntry.from_dict 容错（status 必须 ∈ DAILY_LOG_STATUSES）
# --------------------------------------------------------------------------- #
def test_entry_from_entry_and_dict_roundtrip() -> None:
    entry = DailyLogEntry.from_entry(_entry(1), "2025-01-01T00:00:00Z", C.DAILY_LOG_STATUS_VOCAB)
    assert entry.shown_at == "2025-01-01T00:00:00Z"
    assert entry.status == C.DAILY_LOG_STATUS_VOCAB
    assert DailyLogEntry.from_dict(entry.to_dict()) == entry


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        None,
        [],
        {"id": "n5-0001"},  # 缺字段
        {
            "id": "n5-0001", "level": "N5", "word": "w", "kana": "k",
            "translation": "t", "shown_at": "a", "status": "illegal",  # 非法状态
        },
    ],
)
def test_entry_from_dict_rejects_invalid(bad) -> None:
    assert DailyLogEntry.from_dict(bad) is None


# --------------------------------------------------------------------------- #
# 4. 原子写
# --------------------------------------------------------------------------- #
def test_save_creates_parent_and_no_temp_leftover(store: DailyLogStore) -> None:
    store.add_entry("2025-01-01", _log(1, C.DAILY_LOG_STATUS_MASTERED))
    leftovers = list(store.path.parent.glob("*.tmp")) + list(store.path.parent.glob("daily-log-*"))
    assert leftovers == [], f"原子保存残留临时文件：{leftovers}"
    assert store.path.exists()


def test_save_never_raises_on_bad_path(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    bad = DailyLogStore(blocker / "sub" / "daily_log.json")
    bad.add_entry("2025-01-01", _log(1, C.DAILY_LOG_STATUS_MASTERED))  # 不应抛异常


# --------------------------------------------------------------------------- #
# 5. 损坏处理：备份而非静默清空
# --------------------------------------------------------------------------- #
def test_corrupt_json_is_backed_up_not_cleared(store: DailyLogStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_text = "{ this is not json ]"
    store.path.write_text(corrupt_text, encoding="utf-8")

    assert store.load() == {}
    backups = list(store.path.parent.glob(f"{C.DAILY_LOG_FILE_NAME}.corrupt-*"))
    assert backups, "损坏文件未被备份（数据可能被静默清空）"
    assert backups[0].read_text(encoding="utf-8") == corrupt_text
    assert not store.path.exists()


def test_days_not_object_is_backed_up(store: DailyLogStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"version": 1, "days": "oops"}), encoding="utf-8")
    assert store.load() == {}
    assert list(store.path.parent.glob(f"{C.DAILY_LOG_FILE_NAME}.corrupt-*"))


def test_root_not_object_is_backed_up(store: DailyLogStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("[1, 2, 3]", encoding="utf-8")
    assert store.load() == {}
    assert list(store.path.parent.glob(f"{C.DAILY_LOG_FILE_NAME}.corrupt-*"))


def test_bad_day_bucket_is_skipped_keeping_valid(store: DailyLogStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "days": {
                    "2025-01-01": [DailyLogEntry.from_entry(
                        _entry(1), "t1", C.DAILY_LOG_STATUS_MASTERED
                    ).to_dict()],
                    "2025-01-02": "not-a-list",  # 坏桶 → 跳过
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = store.load()
    assert set(loaded) == {"2025-01-01"}
    assert loaded["2025-01-01"][0].id == "n5-0001"
    assert not list(store.path.parent.glob(f"{C.DAILY_LOG_FILE_NAME}.corrupt-*"))


def test_per_entry_tolerance_keeps_valid(store: DailyLogStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "days": {
                    "2025-01-01": [
                        _log(1, C.DAILY_LOG_STATUS_MASTERED).to_dict(),
                        {"id": "broken"},  # 非法 → 跳过
                    ],
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    loaded = store.load()
    assert len(loaded["2025-01-01"]) == 1
    assert loaded["2025-01-01"][0].id == "n5-0001"
    assert not list(store.path.parent.glob(f"{C.DAILY_LOG_FILE_NAME}.corrupt-*"))


def test_empty_file_is_not_treated_as_corrupt(store: DailyLogStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("   \n", encoding="utf-8")
    assert store.load() == {}
    assert not list(store.path.parent.glob(f"{C.DAILY_LOG_FILE_NAME}.corrupt-*"))
