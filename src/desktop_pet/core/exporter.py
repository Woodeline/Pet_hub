"""core.exporter —— 学习数据导出（纯逻辑，零 Qt、零时钟）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

职责：把既有存储（已掌握词库 / 每日记录）序列化为可交换的文本格式，
**只生成字符串、不做文件 IO**——落盘（编码、对话框、命名）由 app 层完成：

- :func:`to_anki_tsv`：Anki「从文本导入」直接可用的 TSV（首部指令行 +
  制表符分隔 + 标签列），utf-8-sig 落盘后 Excel / Anki 均可无损打开；
- :func:`daily_log_to_csv`：全日期每日学习记录的 CSV（RFC 4180 转义由
  ``csv`` 模块承担）。

时间字段一律是 app 注入的 ISO8601 字符串，本模块原样透传、绝不解析。
"""

from __future__ import annotations

import csv
import io
from typing import Sequence

from desktop_pet.core import constants as C
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.mastered_store import MasteredItem

#: Anki 文本导入首部：制表符分隔、不含 HTML、第 5 列为标签
_ANKI_HEADER: tuple[str, ...] = (
    "#separator:tab",
    "#html:false",
    "#tags column:5",
)
#: Anki 通用标签（便于在 Anki 中按来源筛选）
_ANKI_TAG: str = "desktop-pet"

#: CSV 表头（中文列名，Excel 直接可读）
_DAILY_LOG_CSV_HEADER: tuple[str, ...] = ("日期", "单词", "假名", "翻译", "状态", "展示时间")
_MASTERED_CSV_HEADER: tuple[str, ...] = (
    "单词", "假名", "翻译", "等级", "掌握时间", "记忆阶段", "下次复习", "已复习次数",
)


def _to_tsv_row(fields: Sequence[str]) -> str:
    """单行 TSV：字段内若含制表符 / 换行则替换为空格（数据源不含，防御性处理）。"""

    cleaned = [str(field).replace("\t", " ").replace("\r", " ").replace("\n", " ") for field in fields]
    return "\t".join(cleaned)


def to_anki_tsv(items: Sequence[MasteredItem]) -> str:
    """把已掌握词库导出为 Anki 可导入的 TSV 文本。

    字段：单词 / 假名 / 翻译 / 等级 + 标签列（``desktop-pet N5``）。
    空列表返回仅含首部指令的文本（Anki 导入得到空结果，不报错）。
    """

    lines = list(_ANKI_HEADER)
    for item in items:
        lines.append(
            _to_tsv_row(
                (
                    item.word,
                    item.kana,
                    item.translation,
                    item.level,
                    f"{_ANKI_TAG} {item.level}",
                )
            )
        )
    return "\n".join(lines) + "\n"


def mastered_to_csv(items: Sequence[MasteredItem]) -> str:
    """已掌握词库 → CSV（含 SRS 状态字段，供表格分析）。"""

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(_MASTERED_CSV_HEADER)
    for item in items:
        writer.writerow(
            [
                item.word,
                item.kana,
                item.translation,
                item.level,
                item.mastered_at,
                item.stage,
                item.due_at,
                item.review_count,
            ]
        )
    return buffer.getvalue()


def daily_log_to_csv(log: DailyLogStore) -> str:
    """全部每日学习记录 → CSV（按日期降序、日内按插入顺序）。"""

    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerow(_DAILY_LOG_CSV_HEADER)
    for day in log.days():
        for entry in log.entries_for(day):
            writer.writerow(
                [
                    day,
                    entry.word,
                    entry.kana,
                    entry.translation,
                    entry.status,
                    entry.shown_at,
                ]
            )
    return buffer.getvalue()


__all__ = ["to_anki_tsv", "mastered_to_csv", "daily_log_to_csv"]
