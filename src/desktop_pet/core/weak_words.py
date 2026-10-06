"""core.weak_words —— 错题本（易错词）派生（纯逻辑，零 Qt、零 ``time`` / ``datetime``）。

**不新增任何存储**：从 ``DailyLogStore`` 的 ``review_lapsed`` 条目按词条 id 聚合派生
「反复忘记」的词（遗忘时 mastered 记录整体退回生词本、SRS 状态清空，故
``mastered.json`` 没有失败史——每日记录是唯一的遗忘事实来源，快照含完整词条字段）。

时间口径与各 store 一致：``shown_at`` / ``last_lapsed_at`` 是 app 注入的 ISO8601
定长 UTC 字符串，字典序即时间序，本模块只做字符串比较、绝不解析。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from desktop_pet.core import constants as C
from desktop_pet.core.daily_log_store import DailyLogStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WeakWord:
    """一个易错词的聚合快照（只读，供统计窗口展示与抽取加权）。"""

    id: str
    level: str
    word: str
    kana: str
    translation: str
    #: 累计「忘了」次数（review_lapsed 条数，跨天累计、同日多次也逐次计）
    lapsed_count: int
    #: 最近一次遗忘时间（ISO8601 UTC 字符串；仅用于排序与展示）
    last_lapsed_at: str


def collect_weak_words(
    log: DailyLogStore,
    *,
    min_lapses: int = C.WEAK_WORD_MIN_LAPSES,
    limit: int = C.WEAK_WORD_TOP_N,
) -> tuple[WeakWord, ...]:
    """从每日记录聚合易错词（遗忘次数达到 ``min_lapses`` 才入选）。

    排序：遗忘次数降序，次数相同按最近遗忘时间降序（最近忘的排前面——
    最可能还需要巩固）；超出 ``limit`` 截断（``limit <= 0`` 返回空）。
    """

    if limit <= 0:
        return ()
    counts: dict[str, int] = {}
    last_at: dict[str, str] = {}
    snapshot: dict[str, tuple[str, str, str, str]] = {}
    for day in log.days():
        for entry in log.entries_for(day):
            if entry.status != C.DAILY_LOG_STATUS_REVIEW_LAPSED:
                continue
            key = entry.id
            counts[key] = counts.get(key, 0) + 1
            if key not in last_at or entry.shown_at > last_at[key]:
                last_at[key] = entry.shown_at
            snapshot[key] = (entry.level, entry.word, entry.kana, entry.translation)

    weak: list[WeakWord] = []
    for key, count in counts.items():
        if count < max(1, int(min_lapses)):
            continue
        level, word, kana, translation = snapshot[key]
        weak.append(
            WeakWord(
                id=key,
                level=level,
                word=word,
                kana=kana,
                translation=translation,
                lapsed_count=count,
                last_lapsed_at=last_at[key],
            )
        )
    # 双键排序（Python 排序稳定：先按次键排，再按主键排）——
    # 主键：遗忘次数降序；次键：最近遗忘时间降序（最近忘的排前面，最可能需要巩固）。
    weak.sort(key=lambda item: item.last_lapsed_at, reverse=True)
    weak.sort(key=lambda item: item.lapsed_count, reverse=True)
    result = tuple(weak[: int(limit)])
    if result:
        logger.debug("易错词聚合：%d 个（阈值 %d）", len(result), min_lapses)
    return result


__all__ = ["WeakWord", "collect_weak_words"]
