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
from typing import Any

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)

#: 词条必填字段（均为非空 ``str``）
_REQUIRED_FIELDS: tuple[str, ...] = ("id", "level", "word", "kana", "translation", "meaning")


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


__all__ = ["VocabEntry", "WordBank"]
