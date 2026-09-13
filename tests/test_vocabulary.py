"""词库加载 / 分级索引 / 加权随机抽取 单测（JP-01/06/07/19）。

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
# 3. WordSampler 加权随机抽取（排除已记住 / 生词本加权 / 不连续重复）
# --------------------------------------------------------------------------- #
def test_sampler_returns_none_without_level() -> None:
    sampler = WordSampler(_bank([_entry(1)]), random.Random(0))
    assert sampler.next() is None


def test_sampler_excludes_learned_ids() -> None:
    """标记「记住了」的词条永不出现；全部记住后返回 None。"""

    entries = [_entry(i) for i in range(1, 6)]
    sampler = WordSampler(_bank(entries), random.Random(0))
    sampler.set_level("N5")
    sampler.set_learned_ids({"n5-0001", "n5-0002"})

    drawn = {sampler.next().id for _ in range(60)}
    assert "n5-0001" not in drawn and "n5-0002" not in drawn
    assert drawn <= {"n5-0003", "n5-0004", "n5-0005"}

    sampler.set_learned_ids({f"n5-{i:04d}" for i in range(1, 6)})
    assert sampler.next() is None, "全部记住后仍返回词条"


def test_sampler_boosts_bookmarked_entries() -> None:
    """生词本内词条加权后出现频率显著高于未加权词条（权重 3:1）。

    用 4 词条池：排除「不连续重复」干扰后的理论频率约为
    加权词 0.375 vs 普通词 0.208（比值约 1.8）。
    """

    entries = [_entry(i) for i in range(1, 5)]
    sampler = WordSampler(_bank(entries), random.Random(7))
    sampler.set_level("N5")
    sampler.set_boost_ids({"n5-0001"})

    draws = 3000
    counts: dict[str, int] = {e.id: 0 for e in entries}
    for _ in range(draws):
        counts[sampler.next().id] += 1
    ratio_boosted = counts["n5-0001"] / draws
    ratio_plain = counts["n5-0002"] / draws

    assert ratio_boosted / ratio_plain > 1.4, (
        f"加权未生效：boosted={ratio_boosted:.3f} plain={ratio_plain:.3f}"
    )
    # 加权词应为全池最高频（变异体：权重失效时三项频率趋同，比值≈1，上方断言拦截）
    assert counts["n5-0001"] == max(counts.values())


def test_sampler_no_consecutive_repeat() -> None:
    """池中多于 1 条时不与上一次展示相同。"""

    entries = [_entry(i) for i in range(1, 6)]
    sampler = WordSampler(_bank(entries), random.Random(0))
    sampler.set_level("N5")

    prev = sampler.next().id
    for _ in range(200):
        cur = sampler.next().id
        assert cur != prev, "出现连续重复"
        prev = cur


def test_sampler_single_candidate_still_returned() -> None:
    """池中仅剩 1 条（其余全记住）时仍正常返回该条。"""

    entries = [_entry(1), _entry(2)]
    sampler = WordSampler(_bank(entries), random.Random(0))
    sampler.set_level("N5")
    sampler.set_learned_ids({"n5-0002"})
    for _ in range(5):
        assert sampler.next().id == "n5-0001"


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


def test_sampler_reset_clears_last_id_only() -> None:
    """reset 只清「上次展示」记录，learned/boost 集合与等级保留。"""

    entries = [_entry(i) for i in range(1, 6)]
    sampler = WordSampler(_bank(entries), random.Random(0))
    sampler.set_level("N5")
    sampler.set_learned_ids({"n5-0001"})
    sampler.next()
    sampler.reset()
    got = sampler.next()
    assert got is not None
    assert got.id != "n5-0001", "reset 后仍不应出现已记住词条"


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
