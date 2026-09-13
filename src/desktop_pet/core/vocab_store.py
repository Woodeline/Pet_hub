"""core.vocab_store —— 生词本持久化（原子写 + 逐字段容错读 + 损坏备份）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

设计要点（架构 §7.3）：
- 生词本是**用户数据**，损坏时**绝不静默清空**：先把损坏文件 ``os.replace`` 备份为
  ``<name>.corrupt-<时间戳>`` 再以空列表继续运行（数据由备份保全）。
- 保存采用「``tempfile.mkstemp`` 同目录 + ``flush/fsync`` + ``os.replace`` 原子替换」
  范式（与 :class:`~desktop_pet.core.config.ConfigStore` 同构，刻意复制而不抽取共享工具，
  以避免触碰既有测试）。
- ``added_at`` 由调用方（``app`` 层）注入 ISO8601 UTC 字符串；本模块**不解析时间戳**，
  排序一律按**插入顺序**（新在后），展示时反转。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desktop_pet.core import constants as C
from desktop_pet.core.vocabulary import VocabEntry

logger = logging.getLogger(__name__)

#: 生词本记录必填字段（均为非空 ``str``）
_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "level",
    "word",
    "kana",
    "translation",
    "meaning",
    "added_at",
)


@dataclass(frozen=True)
class VocabItem:
    """生词本中的一条记录（词条冗余快照 + 加入时间，便于离线展示）。"""

    id: str
    level: str
    word: str
    kana: str
    translation: str
    meaning: str
    added_at: str

    @classmethod
    def from_entry(cls, entry: VocabEntry, added_at: str) -> "VocabItem":
        """由词库词条 + 加入时间构造生词记录。"""

        return cls(
            id=entry.id,
            level=entry.level,
            word=entry.word,
            kana=entry.kana,
            translation=entry.translation,
            meaning=entry.meaning,
            added_at=str(added_at),
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {
            "id": self.id,
            "level": self.level,
            "word": self.word,
            "kana": self.kana,
            "translation": self.translation,
            "meaning": self.meaning,
            "added_at": self.added_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "VocabItem | None":
        """逐字段容错构造记录；任一必填非法则返回 ``None``（逐条跳过，保留合法记录）。"""

        if not isinstance(data, dict):
            return None
        values: dict[str, str] = {}
        for key in _REQUIRED_FIELDS:
            raw = data.get(key)
            if not isinstance(raw, str) or not raw.strip():
                return None
            values[key] = raw.strip()
        return cls(
            id=values["id"],
            level=values["level"],
            word=values["word"],
            kana=values["kana"],
            translation=values["translation"],
            meaning=values["meaning"],
            added_at=values["added_at"],
        )


class VocabStore:
    """负责 ``vocabulary.json`` 的容错读取、去重追加与原子保存。"""

    def __init__(self, path: Path) -> None:
        """创建生词本存储。

        Args:
            path: 生词本文件绝对路径。
        """

        self._path: Path = Path(path)
        self._items: list[VocabItem] = []

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    @property
    def path(self) -> Path:
        """生词本文件路径。"""

        return self._path

    @staticmethod
    def default_path() -> Path:
        """返回默认生词本路径 ``%APPDATA%\\desktop-pet\\vocabulary.json``。

        ``APPDATA`` 不可用时回落到用户主目录，保证任何环境下都返回一个可写路径。
        """

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.VOCAB_FILE_NAME

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def load(self) -> list[VocabItem]:
        """容错加载生词本。

        - 文件缺失 / 为空 → 以空列表启动（不备份）。
        - 结构损坏（JSON 解析失败 / 根非对象 / ``items`` 非数组）→ **先备份**再以空列表继续。
        - 逐条非法记录跳过，保留合法记录。
        """

        try:
            if not self._path.exists():
                self._items = []
                return []
            text = self._path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("生词本文件为空：%s（以空生词本启动）", self._path)
                self._items = []
                return []

            data = json.loads(text)
            if not isinstance(data, dict):
                self._backup_corrupt("根节点不是对象")
                self._items = []
                return []

            raw_items = data.get("items")
            if not isinstance(raw_items, list):
                self._backup_corrupt("items 字段不是数组")
                self._items = []
                return []

            items: list[VocabItem] = []
            skipped = 0
            for raw in raw_items:
                item = VocabItem.from_dict(raw)
                if item is None:
                    skipped += 1
                    continue
                items.append(item)

            if skipped:
                logger.warning("生词本 %s 中有 %d 条非法记录被跳过", self._path, skipped)

            self._items = items
            logger.info("生词本加载完成：%s（%d 条）", self._path, len(items))
            return list(items)
        except json.JSONDecodeError as exc:
            self._backup_corrupt(f"JSON 解析失败：{exc}")
            self._items = []
            return []
        except OSError as exc:
            logger.warning("读取生词本失败（%s）：%s（以空生词本启动）", self._path, exc)
            self._items = []
            return []
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载生词本时发生未预期异常（%s），以空生词本启动", self._path)
            self._items = []
            return []

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def items(self) -> list[VocabItem]:
        """返回内部记录列表（按加入顺序，新在后；调用方按需反转展示）。"""

        return self._items

    def contains(self, item_id: str) -> bool:
        """返回是否已存在指定 ``id``。"""

        return any(item.id == item_id for item in self._items)

    def count(self) -> int:
        """返回记录数量。"""

        return len(self._items)

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def add(self, entry: VocabEntry, added_at: str) -> bool:
        """按 ``id`` 去重追加一条；``True`` = 新增，``False`` = 已存在 / 非法。"""

        if entry is None or not getattr(entry, "id", ""):
            return False
        if self.contains(entry.id):
            return False
        self._items.append(VocabItem.from_entry(entry, str(added_at)))
        self.save()
        return True

    def remove(self, item_id: str) -> bool:
        """按 ``id`` 删除一条；``True`` = 已删除，``False`` = 不存在。"""

        for index, item in enumerate(self._items):
            if item.id == item_id:
                del self._items[index]
                self.save()
                return True
        return False

    def clear(self) -> None:
        """清空全部记录并落盘。"""

        self._items = []
        self.save()

    def save(self) -> None:
        """原子保存生词本（``mkstemp`` + ``fsync`` + ``os.replace``）；失败仅记 warning。"""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"version": C.VOCAB_VERSION, "items": [item.to_dict() for item in self._items]},
                ensure_ascii=False,
                indent=2,
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix="vocab-", suffix=".tmp", dir=str(self._path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, self._path)
            except Exception:
                # 清理残留临时文件后继续抛出到外层统一处理
                try:
                    if os.path.exists(tmp_name):
                        os.remove(tmp_name)
                except OSError:
                    pass
                raise
            logger.info("生词本已保存：%s（%d 条）", self._path, len(self._items))
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("保存生词本失败（%s），忽略本次保存", self._path)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _backup_corrupt(self, reason: str) -> None:
        """把损坏的生词本 ``os.replace`` 为 ``<name>.corrupt-<时间戳>``（绝不覆盖旧备份）。"""

        try:
            if not self._path.exists():
                return
            suffix = self._corrupt_suffix()
            target = self._path.with_name(f"{self._path.name}.corrupt-{suffix}")
            counter = 1
            while target.exists():
                target = self._path.with_name(f"{self._path.name}.corrupt-{suffix}-{counter}")
                counter += 1
            os.replace(self._path, target)
            logger.warning("生词本损坏（%s）：%s 已备份为 %s", reason, self._path, target)
        except Exception:  # noqa: BLE001 —— 备份失败也不能让程序崩溃
            logger.exception("备份损坏的生词本失败（%s）", self._path)

    def _corrupt_suffix(self) -> str:
        """生成备份文件名后缀（取损坏文件 mtime 的整数秒）。

        刻意**不 import** ``time`` / ``datetime``（core 时钟无关约定），
        改由 ``os.stat`` 读取文件自身的 mtime 作为确定性时间戳来源。
        """

        try:
            return str(int(os.stat(self._path).st_mtime))
        except OSError:
            return "unknown"


__all__ = ["VocabItem", "VocabStore"]
