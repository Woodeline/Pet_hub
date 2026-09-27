"""core.vocabulary —— 内置词库加载与分级索引。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

边界函数永不抛异常（架构 §7.3）：
- :meth:`WordBank.load` 在文件缺失 / 解析失败 / 结构非法 / 结果为空时一律返回
  :meth:`WordBank.empty`，仅记 ``logger.warning``。
- :meth:`VocabEntry.from_dict` 逐字段校验，任一必填缺失 / 非 ``str`` / 空串即返回
  ``None``（该条被跳过，而非整库失败）。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)

#: 词条必填字段（均为非空 ``str``）
_REQUIRED_FIELDS: tuple[str, ...] = ("id", "level", "word", "kana", "translation", "meaning")


class WordBankParseError(Exception):
    """词库文件结构性非法（读取失败 / JSON 损坏 / 根结构不符 / 无有效词条）。

    与 :meth:`WordBank.load` 的「静默降级为空库」不同，导入路径需要向用户
    反播**拒绝原因**，因此把结构错误显式抛出，由调用方转为通知文案。
    """



@dataclass(frozen=True)
class VocabEntry:
    """一条只读词库词条。

    Attributes:
        id: 全局唯一标识（形如 ``n5-0001``），去重键。
        level: JLPT 等级（``N5/N4/N3/N2/N1``）。
        word: 日语单词（表记，可含汉字 / 假名 / 片假名）。
        kana: 假名读音（全平假名，可含长音符）。
        translation: 简短中文对应词。
        meaning: 中文词性 / 用法说明。
        romaji: 罗马音（存而不显；P2 预留）。
    """

    id: str
    level: str
    word: str
    kana: str
    translation: str
    meaning: str
    romaji: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {
            "id": self.id,
            "level": self.level,
            "word": self.word,
            "kana": self.kana,
            "romaji": self.romaji,
            "translation": self.translation,
            "meaning": self.meaning,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "VocabEntry | None":
        """逐字段容错构造词条；任一必填非法 / 等级越界则返回 ``None``。"""

        if not isinstance(data, dict):
            return None

        values: dict[str, str] = {}
        for key in _REQUIRED_FIELDS:
            raw = data.get(key)
            if not isinstance(raw, str) or not raw.strip():
                return None
            values[key] = raw.strip()

        if values["level"] not in C.JP_LEVELS:
            return None

        romaji_raw = data.get("romaji", "")
        romaji = romaji_raw.strip() if isinstance(romaji_raw, str) else ""

        return cls(
            id=values["id"],
            level=values["level"],
            word=values["word"],
            kana=values["kana"],
            translation=values["translation"],
            meaning=values["meaning"],
            romaji=romaji,
        )


class WordBank:
    """只读词库：持有全部词条并按等级提供索引。"""

    def __init__(self, entries: tuple[VocabEntry, ...]) -> None:
        """以给定词条元组构造词库（一般经 :meth:`load` / :meth:`empty` 创建）。"""

        self._entries: tuple[VocabEntry, ...] = tuple(entries)
        #: 等级 → 词条列表 的惰性索引缓存
        self._by_level: dict[str, list[VocabEntry]] | None = None

    # ------------------------------------------------------------------ #
    # 构造
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: Path) -> "WordBank":
        """从 JSON 文件容错加载词库。

        文件缺失 / 解析失败 / 根非对象 / ``words`` 非数组 / 无有效词条 → 返回空库，
        仅记 ``logger.warning``，绝不抛异常。
        """

        try:
            bank_path = Path(path)
            if not bank_path.exists():
                logger.warning("词库文件不存在：%s（使用空词库）", bank_path)
                return cls.empty()

            text = bank_path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("词库文件为空：%s（使用空词库）", bank_path)
                return cls.empty()

            data = json.loads(text)
            if not isinstance(data, dict):
                logger.warning("词库根节点不是对象：%s（使用空词库）", bank_path)
                return cls.empty()

            raw_words = data.get("words")
            if not isinstance(raw_words, list):
                logger.warning("词库 words 字段不是数组：%s（使用空词库）", bank_path)
                return cls.empty()

            entries: list[VocabEntry] = []
            skipped = 0
            for raw in raw_words:
                entry = VocabEntry.from_dict(raw)
                if entry is None:
                    skipped += 1
                    continue
                entries.append(entry)

            if skipped:
                logger.warning("词库 %s 中有 %d 条非法记录被跳过", bank_path, skipped)

            if not entries:
                logger.warning("词库 %s 无有效词条（使用空词库）", bank_path)
                return cls.empty()

            logger.info("词库加载完成：%s（%d 条）", bank_path, len(entries))
            return cls(tuple(entries))
        except json.JSONDecodeError as exc:
            logger.warning("词库 JSON 解析失败（%s）：%s（使用空词库）", path, exc)
        except OSError as exc:
            logger.warning("读取词库失败（%s）：%s（使用空词库）", path, exc)
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载词库时发生未预期异常（%s），使用空词库", path)
        return cls.empty()

    @classmethod
    def empty(cls) -> "WordBank":
        """返回空词库。"""

        return cls(())

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def entry_by_id(self, item_id: str) -> VocabEntry | None:
        """按全局唯一 ``id`` 查找词条；找不到返回 ``None``。"""

        if not item_id:
            return None
        for entry in self._entries:
            if entry.id == item_id:
                return entry
        return None

    def entries_for(self, level: str) -> list[VocabEntry]:
        """返回指定等级的全部词条（不存在的等级返回空列表）。"""

        if level not in C.JP_LEVELS:
            return []
        if self._by_level is None:
            index: dict[str, list[VocabEntry]] = {lvl: [] for lvl in C.JP_LEVELS}
            for entry in self._entries:
                if entry.level in index:
                    index[entry.level].append(entry)
            self._by_level = index
        return list(self._by_level.get(level, []))

    def levels(self) -> tuple[str, ...]:
        """返回本词库中实际存在的等级（按 :data:`C.JP_LEVELS` 顺序）。"""

        present = {entry.level for entry in self._entries}
        return tuple(level for level in C.JP_LEVELS if level in present)

    def size(self) -> int:
        """返回词条总数。"""

        return len(self._entries)

    def is_empty(self) -> bool:
        """返回词库是否为空（总词条数为 0）。"""

        return not self._entries

    # ------------------------------------------------------------------ #
    # 合并（外置词库 / 用户导入扩充包）
    # ------------------------------------------------------------------ #
    def merge(self, entries: Iterable[VocabEntry]) -> tuple[int, int]:
        """合并一批词条进本词库：按 ``id`` 去重，同 id 用新词条**覆盖**。

        合并后等级索引缓存立即失效，下一次 :meth:`entries_for` 自动重建。

        Args:
            entries: 待合并词条（须已通过 :meth:`VocabEntry.from_dict` 校验）。

        Returns:
            ``(added, updated)``——新增条数与覆盖更新条数。
        """

        added = updated = 0
        index = {entry.id: pos for pos, entry in enumerate(self._entries)}
        merged = list(self._entries)
        for entry in entries:
            pos = index.get(entry.id)
            if pos is None:
                index[entry.id] = len(merged)
                merged.append(entry)
                added += 1
            else:
                merged[pos] = entry
                updated += 1
        if added or updated:
            self._entries = tuple(merged)
            self._by_level = None
        logger.info("词库合并完成：新增 %d，更新 %d（现有 %d 条）", added, updated, len(merged))
        return (added, updated)


def parse_bank_file(path: Path) -> tuple[list[VocabEntry], int]:
    """从 JSON 文件解析词库词条（供导入 / 外置合并路径使用）。

    与 :meth:`WordBank.load` 的区别：结构性错误**显式抛出**
    :class:`WordBankParseError`（调用方需要向用户反馈拒绝原因），而不是静默降级；
    逐条非法记录不计入失败，仅计入跳过数。

    Args:
        path: 词库 JSON 文件路径（``{"version": 1, "words": [...]}`` 结构）。

    Returns:
        ``(entries, skipped)``——有效词条列表与被跳过的非法条数。

    Raises:
        WordBankParseError: 文件不可读 / JSON 损坏 / 根结构不符 / 无任何有效词条。
    """

    bank_path = Path(path)
    try:
        text = bank_path.read_text(encoding="utf-8")
        data = json.loads(text)
    except OSError as exc:
        raise WordBankParseError(f"文件读取失败：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise WordBankParseError(f"JSON 解析失败：{exc}") from exc

    if not isinstance(data, dict):
        raise WordBankParseError("结构不符：根节点需为 JSON 对象")
    raw_words = data.get("words")
    if not isinstance(raw_words, list):
        raise WordBankParseError("结构不符：缺少 words 数组")

    entries: list[VocabEntry] = []
    skipped = 0
    for raw in raw_words:
        entry = VocabEntry.from_dict(raw)
        if entry is None:
            skipped += 1
        else:
            entries.append(entry)
    if not entries:
        raise WordBankParseError(f"无有效词条（{skipped} 条全部非法或为空）")
    return entries, skipped


__all__ = ["VocabEntry", "WordBank", "WordBankParseError", "parse_bank_file"]
