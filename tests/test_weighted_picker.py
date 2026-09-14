"""加权抽取器 单测（JP-17+）：排除 / 权重 3:1 / 空池。

全部为 ``core`` 纯逻辑测试，**不需要 Qt**。通过注入 ``random.Random`` 复现权重。
"""

from __future__ import annotations

import random

from desktop_pet.core import constants as C
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker


def _entry(i: int, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}",
        kana="かな", translation="译", meaning="义",
    )


def _bank() -> WordBank:
    return WordBank(tuple(_entry(i) for i in range(1, 6)))


def test_pick_returns_from_level() -> None:
    picker = WeightedWordPicker(_bank(), random.Random(0))
    entry = picker.pick("N5", set(), set())
    assert entry is not None
    assert entry.level == "N5"


def test_pick_excludes_ids() -> None:
    excluded = {"n5-0001", "n5-0002", "n5-0003", "n5-0004"}
    picker = WeightedWordPicker(_bank(), random.Random(0))
    entry = picker.pick("N5", excluded, set())
    assert entry is not None
    assert entry.id == "n5-0005"


def test_pick_empty_pool_returns_none() -> None:
    all_ids = {_entry(i).id for i in range(1, 6)}
    picker = WeightedWordPicker(_bank(), random.Random(0))
    assert picker.pick("N5", all_ids, set()) is None


def test_pick_unknown_level_returns_none() -> None:
    picker = WeightedWordPicker(_bank(), random.Random(0))
    assert picker.pick("N9", set(), set()) is None


def test_vocab_weight_is_honored() -> None:
    """vocab 词权重 3.0 vs 普通 1.0：多次抽取生词占比应明显更高。"""

    vocab_ids = {"n5-0001"}
    picker = WeightedWordPicker(_bank(), random.Random(12345))
    picks = [picker.pick("N5", set(), vocab_ids) for _ in range(4000)]
    ids = [p.id for p in picks]
    vocab_hits = ids.count("n5-0001")

    # 理论权重：3 / (3 + 4) = 3/7 ≈ 0.4286；普通词各 1/7 ≈ 0.1429
    assert vocab_hits / len(picks) > 0.35, "生词权重未显著生效"


def test_weight_constant_matches_prd() -> None:
    assert C.JP_VOCAB_WEIGHT == 3.0
