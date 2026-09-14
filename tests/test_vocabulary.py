"""词库加载 / 分级索引 / 洗牌非重复抽取 单测（JP-01/06/07/11）。

全部为 ``core`` 纯逻辑测试，**不需要 Qt**。
"""

from __future__ import annotations

import json
import random
import sys
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import paths
from desktop_pet.core.vocabulary import VocabEntry, WordBank, WordSampler


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def _raw(i: int, level: str = "N5", **overrides) -> dict:
    data = {
        "id": f"{level.lower()}-{i:04d}",
        "level": level,
        "word": f"語{i}",
        "kana": "かな",
        "translation": "译",
        "meaning": "义",
    }
    data.update(overrides)
    return data


def _write(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _bank(entries: list[VocabEntry]) -> WordBank:
    return WordBank(tuple(entries))


def _entry(i: int, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}",
        kana="かな", translation="译", meaning="义",
    )


# --------------------------------------------------------------------------- #
# 1. VocabEntry.from_dict 逐字段校验
# --------------------------------------------------------------------------- #
def test_entry_from_dict_valid() -> None:
    entry = VocabEntry.from_dict(_raw(1))
    assert entry is not None
    assert (entry.id, entry.level, entry.word) == ("n5-0001", "N5", "語1")
    assert entry.romaji == ""  # 缺省 romaji 允许省略


@pytest.mark.parametrize(
    "bad",
    [
        "not a dict",
        None,
        [],
        {**_raw(1), "id": ""},
        {**_raw(1), "level": ""},
        {**_raw(1), "word": "   "},
        {**_raw(1), "kana": ""},
        {**_raw(1), "translation": None},
        {**_raw(1), "meaning": 123},
        {**_raw(1), "level": "N9"},   # 非法等级
    ],
)
def test_entry_from_dict_rejects_invalid(bad) -> None:
    assert VocabEntry.from_dict(bad) is None


def test_entry_to_dict_roundtrip() -> None:
    entry = VocabEntry.from_dict(_raw(1))
    assert entry is not None
    again = VocabEntry.from_dict(entry.to_dict())
    assert again == entry


# --------------------------------------------------------------------------- #
# 2. WordBank.load 容错
# --------------------------------------------------------------------------- #
def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    bank = WordBank.load(tmp_path / "nope.json")
    assert bank.is_empty() and bank.size() == 0


def test_load_invalid_json_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "bad.json"
    p.write_text("{ not json ]", encoding="utf-8")
    assert WordBank.load(p).is_empty()


def test_load_non_object_root_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "arr.json"
    _write(p, [1, 2, 3])
    assert WordBank.load(p).is_empty()


def test_load_words_not_list_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    _write(p, {"version": 1, "words": "oops"})
    assert WordBank.load(p).is_empty()


def test_load_empty_words_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    _write(p, {"version": 1, "words": []})
    assert WordBank.load(p).is_empty()


def test_load_skips_invalid_records_keeps_valid(tmp_path: Path) -> None:
    p = tmp_path / "x.json"
    _write(
        p,
        {
            "version": 1,
            "words": [
                _raw(1),
                {"id": "n5-0002"},            # 缺字段 → 跳过
                {**_raw(3), "level": "N9"},   # 非法等级 → 跳过
                _raw(4, level="N4"),
            ],
        },
    )
    bank = WordBank.load(p)
    assert bank.size() == 2
    assert bank.levels() == ("N5", "N4")


def test_load_real_builtin_bank_has_all_levels() -> None:
    from desktop_pet.core import paths

    bank = WordBank.load(paths.word_bank_path())
    assert not bank.is_empty()
    assert bank.levels() == C.JP_LEVELS
    for level in C.JP_LEVELS:
        assert len(bank.entries_for(level)) >= 100


def test_entries_for_unknown_level_returns_empty() -> None:
    b = _bank([_entry(1)])
    assert b.entries_for("N9") == []


# --------------------------------------------------------------------------- #
# 3. WordSampler 洗牌非重复
# --------------------------------------------------------------------------- #
def test_sampler_returns_none_without_level() -> None:
    sampler = WordSampler(_bank([_entry(1)]), random.Random(0))
    assert sampler.next() is None


def test_sampler_first_round_no_repeat_and_cross_round_differs() -> None:
    entries = [_entry(i) for i in range(1, 4)]
    sampler = WordSampler(_bank(entries), random.Random(0))
    sampler.set_level("N5")

    first_round = [sampler.next() for _ in range(3)]
    ids = [e.id for e in first_round if e is not None]
    assert len(ids) == 3
    assert len(set(ids)) == 3, "同一轮内出现重复"

    # 新一轮首词 ≠ 上轮末词
    nxt = sampler.next()
    assert nxt is not None
    assert nxt.id != ids[-1], "新一轮首词与上轮末词相同"

    # 新一轮同样不重复
    second_round = [nxt] + [sampler.next() for _ in range(2)]
    ids2 = [e.id for e in second_round if e is not None]
    assert len(set(ids2)) == 3


def test_sampler_set_level_switches_pool() -> None:
    entries = [_entry(1, "N5"), _entry(2, "N5"), _entry(1, "N4")]
    sampler = WordSampler(_bank(entries), random.Random(1))
    sampler.set_level("N5")
    assert sampler.next().level == "N5"
    sampler.set_level("N4")
    got = sampler.next()
    assert got is not None and got.level == "N4"


def test_sampler_invalid_level_is_noop() -> None:
    sampler = WordSampler(_bank([_entry(1)]), random.Random(0))
    sampler.set_level("N5")
    sampler.set_level("XX")  # 非法 → no-op
    assert sampler.next() is not None


def test_sampler_level_without_words_returns_none() -> None:
    sampler = WordSampler(_bank([_entry(1, "N5")]), random.Random(0))
    sampler.set_level("N1")  # 合法但该级无词
    assert sampler.next() is None


def test_sampler_reset_forces_reshuffle() -> None:
    entries = [_entry(i) for i in range(1, 4)]
    sampler = WordSampler(_bank(entries), random.Random(0))
    sampler.set_level("N5")
    sampler.next()
    sampler.reset()
    assert sampler.next() is not None


# --------------------------------------------------------------------------- #
# 4. core.paths 路径解析（源码 / 冻结）
# --------------------------------------------------------------------------- #
def test_word_bank_path_source_mode(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    path = paths.word_bank_path()
    assert path.name == C.WORD_BANK_FILE_NAME
    assert path.parent.name == C.WORD_BANK_DIR_NAME
    assert "desktop_pet" in path.parts
    assert not paths.is_frozen()


def test_word_bank_path_frozen_mode(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert paths.is_frozen()
    assert paths.word_bank_path() == tmp_path / "desktop_pet" / C.WORD_BANK_DIR_NAME / C.WORD_BANK_FILE_NAME
