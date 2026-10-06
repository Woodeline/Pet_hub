"""工程师自测：core.exporter —— 导出纯逻辑（Anki TSV / CSV）。

覆盖：
1. Anki TSV：首部指令行、字段顺序、标签列、空数据、字段清洗（制表符/换行）。
2. CSV：表头、字段完整（含 SRS 状态）、逗号转义（csv 模块引号包裹）、
   日期降序、行内容与存储一致。

core 零时钟约定：时间字段由测试注入字符串，原样透传。
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.exporter import daily_log_to_csv, mastered_to_csv, to_anki_tsv
from desktop_pet.core.mastered_store import MasteredItem


def _item(word_id: int, word: str = "語", translation: str = "译") -> MasteredItem:
    return MasteredItem(
        id=f"n5-{word_id:04d}",
        level="N5",
        word=f"{word}{word_id}",
        kana="かな",
        translation=translation,
        mastered_at="2025-01-01T00:00:00Z",
        stage=2,
        due_at="2025-01-08T00:00:00Z",
        review_count=1,
    )


def _parse_csv(text: str) -> list[list[str]]:
    reader = csv.reader(io.StringIO(text))
    return list(reader)


# --------------------------------------------------------------------------- #
# Anki TSV
# --------------------------------------------------------------------------- #
def test_anki_tsv_header_and_rows() -> None:
    """首部指令行 + 每词一行：单词/假名/翻译/等级 + 标签列。"""

    text = to_anki_tsv([_item(1), _item(2)])
    lines = text.splitlines()
    assert lines[0] == "#separator:tab"
    assert lines[1] == "#html:false"
    assert lines[2] == "#tags column:5"
    fields = lines[3].split("\t")
    assert fields == ["語1", "かな", "译", "N5", "desktop-pet N5"]
    assert len(lines) == 5


def test_anki_tsv_empty_items_returns_header_only() -> None:
    """空列表：仅首部指令（Anki 导入得空结果，不报错）。"""

    lines = to_anki_tsv([]).splitlines()
    assert lines == ["#separator:tab", "#html:false", "#tags column:5"]


def test_anki_tsv_sanitizes_tab_and_newline() -> None:
    """字段含制表符 / 换行：替换为空格（保证 TSV 行结构不被破坏）。"""

    item = _item(1, translation="坏\t字段\n值")
    fields = to_anki_tsv([item]).splitlines()[3].split("\t")
    assert fields[2] == "坏 字段 值"
    assert len(fields) == 5


# --------------------------------------------------------------------------- #
# CSV
# --------------------------------------------------------------------------- #
def test_mastered_csv_header_and_fields() -> None:
    """表头 + 全字段（含 SRS：阶段 / 下次复习 / 复习次数）。"""

    rows = _parse_csv(mastered_to_csv([_item(1)]))
    assert rows[0] == ["单词", "假名", "翻译", "等级", "掌握时间", "记忆阶段", "下次复习", "已复习次数"]
    assert rows[1] == ["語1", "かな", "译", "N5", "2025-01-01T00:00:00Z", "2", "2025-01-08T00:00:00Z", "1"]


def test_mastered_csv_escapes_comma() -> None:
    """翻译含逗号：csv 模块自动引号包裹，解析后无损还原。"""

    rows = _parse_csv(mastered_to_csv([_item(1, translation="A, B")]))
    assert rows[1][2] == "A, B"


def test_daily_log_csv_ordered_desc_with_raw_status(tmp_path: Path) -> None:
    """全部日期按降序输出；状态列导出原始值（稳定机器口径）。"""

    store = DailyLogStore(tmp_path / "daily_log.json")
    store.load()
    for day in ("2025-01-01", "2025-01-02"):
        store.add_entry(
            day,
            DailyLogEntry(
                id="n5-0001",
                level="N5",
                word="語",
                kana="かな",
                translation="译",
                shown_at=f"{day}T00:00:00Z",
                status="review_lapsed",
            ),
        )

    rows = _parse_csv(daily_log_to_csv(store))
    assert rows[0] == ["日期", "单词", "假名", "翻译", "状态", "展示时间"]
    assert [row[0] for row in rows[1:]] == ["2025-01-02", "2025-01-01"]
    assert rows[1][4] == "review_lapsed"
    assert rows[1][1] == "語"


def test_daily_log_csv_empty_store(tmp_path: Path) -> None:
    """空记录：仅表头。"""

    store = DailyLogStore(tmp_path / "daily_log.json")
    store.load()
    rows = _parse_csv(daily_log_to_csv(store))
    assert rows == [["日期", "单词", "假名", "翻译", "状态", "展示时间"]]
