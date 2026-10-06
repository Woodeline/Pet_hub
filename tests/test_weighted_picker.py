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


def test_boost_weight_is_honored() -> None:
    """易错词加权（错题本 TopN）：boost 叠乘既有权重，占比显著抬升。"""

    boost_ids = {"n5-0001"}
    picker = WeightedWordPicker(_bank(), random.Random(12345))
    picks = [picker.pick("N5", set(), set(), boost_ids=boost_ids) for _ in range(4000)]
    ids = [p.id for p in picks]
    boost_hits = ids.count("n5-0001")

    # 理论权重：2 / (4 + 2) = 1/3 ≈ 0.333（boost 2.0 叠乘普通权重 1.0）
    assert boost_hits / len(picks) > 0.25, "易错词 boost 权重未显著生效"


def test_boost_multiplies_vocab_weight() -> None:
    """生词 + 易错词叠乘（3.0 × 2.0 = 6.0）：占比应高于仅生词加权。"""

    vocab_ids = {"n5-0001"}
    boost_ids = {"n5-0001"}
    plain = WeightedWordPicker(_bank(), random.Random(12345))
    boosted = WeightedWordPicker(_bank(), random.Random(12345))
    plain_hits = sum(
        1 for _ in range(4000) if plain.pick("N5", set(), vocab_ids).id == "n5-0001"
    )
    boosted_hits = sum(
        1
        for _ in range(4000)
        if boosted.pick("N5", set(), vocab_ids, boost_ids=boost_ids).id == "n5-0001"
    )
    # 理论：3/7 ≈ 0.4286 → 6/(6+4) = 0.6；同 rng 序列下叠乘应明显更高
    assert boosted_hits > plain_hits


def test_boost_empty_set_is_noop() -> None:
    """boost_ids 为空集合 / None：与不传完全同分布（同 rng 同结果序列）。"""

    a = WeightedWordPicker(_bank(), random.Random(7))
    b = WeightedWordPicker(_bank(), random.Random(7))
    for _ in range(200):
        ea = a.pick("N5", set(), {"n5-0002"}, boost_ids=set())
        eb = b.pick("N5", set(), {"n5-0002"})
        assert ea is not None and eb is not None
        assert ea.id == eb.id
