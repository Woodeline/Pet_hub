"""core.stats_aggregator —— 学习统计聚合（纯逻辑，零 Qt、零 ``time`` / ``datetime``）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得自取时钟。**

全部时间输入由 app 层注入，与各 store 的既有约定一致：

- ``day_keys``：**升序**（旧 → 新）的本地自然日字符串序列（``YYYY-MM-DD``），
  本模块只把它当**有序分桶 key**，绝不解析日期、绝不自取时钟；
- 掌握曲线按 ``MasteredItem.mastered_at`` 的**前 10 位**字符串分桶
  （ISO8601 定长 UTC，字典序即时间序，见 ``daily_log_store`` / ``controller._iso_*``）。

聚合结果 :class:`StatsSummary` 是冻结数据类，供 ``ui.stats_window`` 纯展示，
不含任何业务判定（配额判定仍在 controller）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Sequence

from desktop_pet.core import constants as C
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.mastered_store import MasteredItem

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StatsSummary:
    """一段日期窗口内的学习统计聚合结果（全部只读，供统计窗口直接展示）。"""

    #: 升序日期 key（与注入序列一致；窗口外的历史日期不出现）
    day_keys: tuple[str, ...]
    #: 每日**新词**数（``new_word_count_for`` 口径：不含复习两态）
    new_words: dict[str, int]
    #: 每日复习「记得」数（``review_ok``）
    review_ok: dict[str, int]
    #: 每日复习「忘了」数（``review_lapsed``）
    review_lapsed: dict[str, int]
    #: 连续打卡天数（口径见 :func:`count_streak`）
    streak_days: int
    #: 累计掌握曲线：``((day_key, 截至 <= 当日的累计掌握数), ...)`` 升序
    mastered_curve: tuple[tuple[str, int], ...]
    #: 窗口末日的累计掌握总数（= 曲线末值；含窗口前掌握的历史词）
    total_mastered: int


def count_streak(log: DailyLogStore, day_keys: Sequence[str]) -> int:
    """连续打卡天数：从最近一天往前数「有学习记录」的连续天数。

    打卡口径 = 当日 ``DailyLogStore.count_for(day) > 0``（任何一种记录都算学过）。

    「当日未学不断签」：若序列最后一天（今天）暂无记录，则从倒数第二天
    （昨天）继续往前数 —— 今天还没过完，不应把之前的连胜清零；
    但只要今天学了，连胜即包含今天。序列为空返回 0。
    """

    keys = [str(key) for key in day_keys]
    if not keys:
        return 0
    index = len(keys) - 1
    if log.count_for(keys[index]) == 0:
        index -= 1
    streak = 0
    while index >= 0 and log.count_for(keys[index]) > 0:
        streak += 1
        index -= 1
    return streak


def build_summary(
    log: DailyLogStore,
    mastered_items: Sequence[MasteredItem],
    day_keys: Sequence[str],
) -> StatsSummary:
    """聚合一段日期窗口内的统计（全部输入由调用方注入，本函数不自取时钟）。

    Args:
        log: 已加载的每日记录存储。
        mastered_items: 已掌握记录列表（取 ``mastered_at`` 分桶画累计曲线）。
        day_keys: **升序**本地自然日序列（旧 → 新，末位通常为今天）。

    Returns:
        :class:`StatsSummary`（冻结数据类）。
    """

    keys = tuple(str(key) for key in day_keys)

    new_words: dict[str, int] = {}
    review_ok: dict[str, int] = {}
    review_lapsed: dict[str, int] = {}
    for key in keys:
        entries = log.entries_for(key)
        new_words[key] = sum(
            1
            for entry in entries
            if entry.status not in (C.DAILY_LOG_STATUS_REVIEW_OK, C.DAILY_LOG_STATUS_REVIEW_LAPSED)
        )
        review_ok[key] = sum(
            1 for entry in entries if entry.status == C.DAILY_LOG_STATUS_REVIEW_OK
        )
        review_lapsed[key] = sum(
            1 for entry in entries if entry.status == C.DAILY_LOG_STATUS_REVIEW_LAPSED
        )

    curve = _mastered_curve(mastered_items, keys)
    total = curve[-1][1] if curve else 0
    summary = StatsSummary(
        day_keys=keys,
        new_words=new_words,
        review_ok=review_ok,
        review_lapsed=review_lapsed,
        streak_days=count_streak(log, keys),
        mastered_curve=curve,
        total_mastered=total,
    )
    logger.debug(
        "学习统计聚合完成：%d 天窗口，打卡 %d 天，累计掌握 %d",
        len(keys), summary.streak_days, summary.total_mastered,
    )
    return summary


def _mastered_curve(
    mastered_items: Sequence[MasteredItem], keys: tuple[str, ...]
) -> tuple[tuple[str, int], ...]:
    """累计掌握曲线：``mastered_at`` 前 10 位分桶后对窗口日期做前缀和。

    窗口开始**之前**掌握的词也计入（曲线起点即含历史存量）；``mastered_at``
    落在窗口之后（时钟回拨等异常）的记录不计入曲线，但总数以曲线末值为准。
    """

    if not keys:
        return ()
    counts_by_day: dict[str, int] = {}
    for item in mastered_items:
        day = str(item.mastered_at)[:10]
        counts_by_day[day] = counts_by_day.get(day, 0) + 1
    mastered_days = sorted(counts_by_day)
    curve: list[tuple[str, int]] = []
    cumulative = 0
    pointer = 0
    for key in keys:
        while pointer < len(mastered_days) and mastered_days[pointer] <= key:
            cumulative += counts_by_day[mastered_days[pointer]]
            pointer += 1
        curve.append((key, cumulative))
    return tuple(curve)


__all__ = ["StatsSummary", "count_streak", "build_summary"]
