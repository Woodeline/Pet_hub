"""core.corrections_store —— 词库纠错覆盖层持久化（原子写 + 逐字段容错读 + 损坏备份）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

设计要点（与 :class:`~desktop_pet.core.vocab_store.VocabStore` 完全同构；刻意复制，
不抽取共享工具，以免触碰既有测试）：
- 纠错记录是**用户数据**，损坏时**绝不静默清空**：先把损坏文件 ``os.replace`` 备份为
  ``<name>.corrupt-<时间戳>`` 再以空列表继续运行（数据由备份保全）。
- 保存采用「``tempfile.mkstemp`` 同目录 + ``flush/fsync`` + ``os.replace`` 原子替换」。
- 覆盖层语义：记录「某词条某字段 → 新值」，**词库文件本身永不改写**——内置词库是
  打包只读资源，外置库是用户原始导入件；每次合并词库后由 app 层统一套用覆盖
  （``Controller._apply_corrections``），撤销 = 删记录后重建词库并按 ``old_value``
  还原快照。
- 键为 ``(id, field)``，重复纠错同字段走 **upsert**；``old_value`` 恒为最初原值
  （重复纠错不覆盖它），保证撤销可还原到纠错前。
- ``created_at`` 由调用方（``app`` 层）注入 ISO8601 UTC 字符串；本模块不解析时间戳。

已知取舍：OpenJLPT 词条 id 由 ``md5(word + reading)`` 生成（``scripts/build_openjlpt_bank.py``），
上游重建词库后 id 可能变化导致该词纠错失联（加载时告警跳过）——与多词库
「同 id 后者覆盖」的合并语义一致，纠错按 ``id`` 全局生效，不做按库隔离。
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

logger = logging.getLogger(__name__)

#: 纠错记录必填字段（均为非空 ``str``）
_REQUIRED_FIELDS: tuple[str, ...] = ("id", "word", "field", "old_value", "new_value")


@dataclass(frozen=True)
class CorrectionItem:
    """一条词条纠错记录（覆盖层：字段 → 新值；``old_value`` 供撤销还原）。

    Attributes:
        id: 词条唯一标识（形如 ``n5-0001`` / ``ojl-<hash>``）。
        word: 表记快照（仅用于展示与日志，不参与匹配）。
        field: 被纠错的字段名（``C.CORRECTION_FIELDS`` 之一）。
        old_value: 最初原值（重复纠错时保持不变）。
        new_value: 纠错后值。
        note: 用户备注（可选）。
        created_at: 记录时间（ISO8601 UTC，app 层注入）。
    """

    id: str
    word: str
    field: str
    old_value: str
    new_value: str
    note: str = ""
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {
            "id": self.id,
            "word": self.word,
            "field": self.field,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "note": self.note,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "CorrectionItem | None":
        """逐字段容错构造记录；任一必填非法 / 字段名越界则返回 ``None``（逐条跳过）。"""

        if not isinstance(data, dict):
            return None
        values: dict[str, str] = {}
        for key in _REQUIRED_FIELDS:
            raw = data.get(key)
            if not isinstance(raw, str) or not raw.strip():
                return None
            values[key] = raw.strip()
        if values["field"] not in C.CORRECTION_FIELDS:
            return None

        note_raw = data.get("note", "")
        note = note_raw.strip() if isinstance(note_raw, str) else ""
        created_raw = data.get("created_at", "")
        created_at = created_raw.strip() if isinstance(created_raw, str) else ""

        return cls(
            id=values["id"],
            word=values["word"],
            field=values["field"],
            old_value=values["old_value"],
            new_value=values["new_value"],
            note=note,
            created_at=created_at,
        )


class CorrectionStore:
    """负责 ``corrections.json`` 的容错读取、按 ``(id, field)`` 覆盖写入与原子保存。"""

    def __init__(self, path: Path) -> None:
        """创建纠错记录存储。

        Args:
            path: 纠错记录文件绝对路径。
        """

        self._path: Path = Path(path)
        self._items: list[CorrectionItem] = []

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    @property
    def path(self) -> Path:
        """纠错记录文件路径。"""

        return self._path

    @staticmethod
    def default_path() -> Path:
        """返回默认路径 ``%APPDATA%\\desktop-pet\\corrections.json``。

        ``APPDATA`` 不可用时回落到用户主目录，保证任何环境下都返回一个可写路径。
        """

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.CORRECTIONS_FILE_NAME

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def load(self) -> list[CorrectionItem]:
        """容错加载纠错记录。

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
                logger.warning("纠错记录文件为空：%s（以空记录启动）", self._path)
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

            items: list[CorrectionItem] = []
            skipped = 0
            for raw in raw_items:
                item = CorrectionItem.from_dict(raw)
                if item is None:
                    skipped += 1
                    continue
                items.append(item)

            if skipped:
                logger.warning("纠错记录 %s 中有 %d 条非法记录被跳过", self._path, skipped)

            self._items = items
            logger.info("纠错记录加载完成：%s（%d 条）", self._path, len(items))
            return list(items)
        except json.JSONDecodeError as exc:
            self._backup_corrupt(f"JSON 解析失败：{exc}")
            self._items = []
            return []
        except OSError as exc:
            logger.warning("读取纠错记录失败（%s）：%s（以空记录启动）", self._path, exc)
            self._items = []
            return []
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载纠错记录时发生未预期异常（%s），以空记录启动", self._path)
            self._items = []
            return []

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def items(self) -> list[CorrectionItem]:
        """返回全部纠错记录（按写入顺序，新在后）。"""

        return self._items

    def items_for(self, item_id: str) -> list[CorrectionItem]:
        """返回指定词条的全部纠错记录（供对话框展示与撤销）。"""

        return [item for item in self._items if item.id == str(item_id)]

    def count(self) -> int:
        """返回记录数量。"""

        return len(self._items)

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def upsert(self, item: CorrectionItem) -> None:
        """按 ``(id, field)`` 覆盖写入一条纠错（无则追加，有则替换）并落盘。

        重复纠错同字段时**保留新记录的 ``old_value``**：调用方（app 层）负责传入
        词库当前值——覆盖层生效后即最初原值，保证撤销可还原。
        """

        if item is None or not getattr(item, "id", "") or not getattr(item, "field", ""):
            return
        for index, existing in enumerate(self._items):
            if existing.id == item.id and existing.field == item.field:
                self._items[index] = item
                self.save()
                return
        self._items.append(item)
        self.save()

    def remove(self, item_id: str, field: str) -> CorrectionItem | None:
        """按 ``(id, field)`` 删除一条纠错并落盘；返回被删记录（撤销还原用），无则 ``None``。"""

        for index, existing in enumerate(self._items):
            if existing.id == str(item_id) and existing.field == str(field):
                removed = self._items.pop(index)
                self.save()
                return removed
        return None

    def clear(self) -> None:
        """清空全部记录并落盘。"""

        self._items = []
        self.save()

    def save(self) -> None:
        """原子保存纠错记录（``mkstemp`` + ``fsync`` + ``os.replace``）；失败仅记 warning。"""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"version": C.CORRECTIONS_VERSION, "items": [item.to_dict() for item in self._items]},
                ensure_ascii=False,
                indent=2,
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix="corrections-", suffix=".tmp", dir=str(self._path.parent)
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
            logger.info("纠错记录已保存：%s（%d 条）", self._path, len(self._items))
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("保存纠错记录失败（%s），忽略本次保存", self._path)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _backup_corrupt(self, reason: str) -> None:
        """把损坏的文件 ``os.replace`` 为 ``<name>.corrupt-<时间戳>``（绝不覆盖旧备份）。"""

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
            logger.warning("纠错记录损坏（%s）：%s 已备份为 %s", reason, self._path, target)
        except Exception:  # noqa: BLE001 —— 备份失败也不能让程序崩溃
            logger.exception("备份损坏的纠错记录失败（%s）", self._path)

    def _corrupt_suffix(self) -> str:
        """生成备份文件名后缀（取损坏文件 mtime 的整数秒）。

        刻意**不 import** ``time`` / ``datetime``（core 时钟无关约定），
        改由 ``os.stat`` 读取文件自身的 mtime 作为确定性时间戳来源。
        """

        try:
            return str(int(os.stat(self._path).st_mtime))
        except OSError:
            return "unknown"


__all__ = ["CorrectionItem", "CorrectionStore"]
