"""core.weighted_picker —— 记忆闭环的加权随机抽取器（纯逻辑，零 Qt 零 time）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

无状态：排除集 / 生词集由调用方（``app`` 层）每次传入，跨日 / 跨等级自然由调用方决定。
"""

from __future__ import annotations

import random

from desktop_pet.core import constants as C
from desktop_pet.core.vocabulary import VocabEntry, WordBank


class WeightedWordPicker:
    """在指定等级内，排除已掌握 / 当日已展示后按权重抽取一条词条。"""

    def __init__(self, bank: WordBank, rng: random.Random | None = None) -> None:
        """构造抽取器。

        Args:
            bank: 词库。
            rng: 随机源（可注入以便测试复现）；``None`` 时新建独立 ``random.Random``。
        """

        self._bank: WordBank = bank
        self._rng: random.Random = rng if rng is not None else random.Random()

    def pick(
        self, level: str, excluded_ids: set[str], vocab_ids: set[str]
    ) -> VocabEntry | None:
        """抽取一条词条。

        Args:
            level: JLPT 等级（``N5..N1``）。
            excluded_ids: 需排除的词条 id 集合（已掌握 ∪ 当日已展示）。
            vocab_ids: 生词 id 集合（权重 ``C.JP_VOCAB_WEIGHT``，普通词条权重 1.0）。

        Returns:
            抽中的词条；候选池为空返回 ``None``。
        """

        pool = [entry for entry in self._bank.entries_for(level) if entry.id not in excluded_ids]
        if not pool:
            return None
        weights = [C.JP_VOCAB_WEIGHT if entry.id in vocab_ids else 1.0 for entry in pool]
        return self._rng.choices(pool, weights=weights, k=1)[0]


__all__ = ["WeightedWordPicker"]
