"""core.bank_registry —— 多词库登记表（store 范式：原子写 + 逐字段容错读 + 损坏备份）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

多词库模型（批次 7）：

- 每个导入的词库独立存为 ``banks/<bank_id>.json``（文件名 = 记录 id，由本模块
  生成与命名，调用方不自行拼路径）；
- ``bank_registry.json`` 登记元数据：``{"version": 1, "banks": [BankRecord...]}``；
- 合并顺序 = ``added_at`` 升序（同 id 词条**后来者覆盖**——最后导入的词库优先，
  与旧版「外置覆盖内置」语义一致）；内置词库恒为合并底座、不在本表登记；
- ``added_at`` 是 app 注入的 ISO8601 UTC 字符串，仅作排序 key（字典序即时间序）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BankRecord:
    """登记表中的一条词库记录（只读快照）。"""

    id: str          # 形如 ``bk-<10 位十六进制>``；同时是 banks/ 下的文件名（去 .json）
    name: str        # 展示名（默认取导入文件 stem）
    file: str        # banks/ 下的文件名（``<id>.json``，不含路径分隔符）
    enabled: bool    # 停用的词库不参与合并（文件保留）
    added_at: str    # ISO8601 UTC 字符串（合并顺序 key，字典序即时间序）


@dataclass(frozen=True)
class BankInfo:
    """词库管理窗口的展示信息（由 controller 聚合喂入，UI 不读存储）。"""

    id: str
    name: str
    enabled: bool
    builtin: bool
    word_count: int
    level_counts: dict[str, int]


class BankRegistryStore:
    """负责 ``bank_registry.json`` 的容错读取、登记变更与原子保存。"""

    def __init__(self, path: Path) -> None:
        """创建登记表存储。

        Args:
            path: 登记表文件绝对路径。
        """

        self._path: Path = Path(path)
        self._records: list[BankRecord] = []

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    @property
    def path(self) -> Path:
        """登记表文件路径。"""

        return self._path

    @staticmethod
    def default_path() -> Path:
        """返回默认路径 ``%APPDATA%\\desktop-pet\\bank_registry.json``。"""

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.BANK_REGISTRY_FILENAME

    @staticmethod
    def banks_dir() -> Path:
        """返回词库文件目录 ``%APPDATA%\\desktop-pet\\banks\\``（意图路径，不抛）。"""

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.BANKS_DIR_NAME

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def load(self) -> tuple[BankRecord, ...]:
        """容错加载登记表（损坏先备份再以空表继续，绝不静默清空数据文件）。"""

        try:
            if not self._path.exists():
                self._records = []
                return ()
            text = self._path.read_text(encoding="utf-8")
            if not text.strip():
                self._records = []
                return ()
            data = json.loads(text)
            if not isinstance(data, dict) or not isinstance(data.get("banks"), list):
                self._backup_corrupt("根节点或 banks 字段非法")
                self._records = []
                return ()

            records: list[BankRecord] = []
            seen_ids: set[str] = set()
            skipped = 0
            for raw in data["banks"]:
                record = self._record_from_dict(raw)
                if record is None or record.id in seen_ids:
                    skipped += 1
                    continue
                seen_ids.add(record.id)
                records.append(record)
            if skipped:
                logger.warning("词库登记表有 %d 条非法/重复记录被跳过", skipped)
            self._records = records
            logger.info("词库登记表加载完成：%s（%d 条）", self._path, len(records))
            return tuple(records)
        except json.JSONDecodeError as exc:
            self._backup_corrupt(f"JSON 解析失败：{exc}")
            self._records = []
            return ()
        except OSError as exc:
            logger.warning("读取词库登记表失败（%s）：%s（以空表继续）", self._path, exc)
            self._records = []
            return ()
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载词库登记表未预期异常（%s）", self._path)
            self._records = []
            return ()

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def records(self) -> tuple[BankRecord, ...]:
        """全部记录（按 ``added_at`` 升序 = 合并顺序；先导入先合并、后被覆盖）。"""

        return tuple(sorted(self._records, key=lambda record: record.added_at))

    def get(self, bank_id: str) -> BankRecord | None:
        """按 id 查记录；不存在返回 ``None``。"""

        key = str(bank_id)
        for record in self._records:
            if record.id == key:
                return record
        return None

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def add(self, name: str, added_at: str) -> BankRecord:
        """登记新词库：生成 id 与 ``<id>.json`` 文件名并落盘。

        Args:
            name: 展示名（调用方保证非空；空白折叠为单空格）。
            added_at: ISO8601 UTC 字符串（app 注入）。

        Returns:
            新建的 :class:`BankRecord`。
        """

        clean_name = " ".join(str(name).split()) or "导入词库"
        iso = str(added_at)
        bank_id = "bk-" + hashlib.md5(f"{clean_name}\x1f{iso}".encode("utf-8")).hexdigest()[:10]
        # id 碰撞（同秒同名导入）：追加序号重算，保持 id 唯一
        suffix = 1
        while self.get(bank_id) is not None:
            suffix += 1
            bank_id = "bk-" + hashlib.md5(
                f"{clean_name}\x1f{iso}\x1f{suffix}".encode("utf-8")
            ).hexdigest()[:10]
        record = BankRecord(
            id=bank_id,
            name=clean_name,
            file=f"{bank_id}.json",
            enabled=True,
            added_at=iso,
        )
        self._records.append(record)
        self.save()
        return record

    def set_enabled(self, bank_id: str, enabled: bool) -> bool:
        """更新启用态并落盘；记录不存在返回 ``False``。"""

        for index, record in enumerate(self._records):
            if record.id == str(bank_id):
                if record.enabled == bool(enabled):
                    return True
                updated = BankRecord(
                    id=record.id,
                    name=record.name,
                    file=record.file,
                    enabled=bool(enabled),
                    added_at=record.added_at,
                )
                self._records[index] = updated
                self.save()
                return True
        return False

    def remove(self, bank_id: str) -> BankRecord | None:
        """移除记录并落盘；返回被移除的记录（不存在返回 ``None``）。

        词库**文件**的删除由调用方负责（本模块只管登记表）。
        """

        key = str(bank_id)
        removed: BankRecord | None = None
        remaining: list[BankRecord] = []
        for record in self._records:
            if record.id == key:
                removed = record
                continue
            remaining.append(record)
        if removed is not None:
            self._records = remaining
            self.save()
        return removed

    def save(self) -> None:
        """原子保存（``mkstemp`` + ``fsync`` + ``os.replace``）；失败仅记 warning。"""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "version": C.BANK_REGISTRY_VERSION,
                    "banks": [
                        {
                            "id": record.id,
                            "name": record.name,
                            "file": record.file,
                            "enabled": record.enabled,
                            "added_at": record.added_at,
                        }
                        for record in self._records
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix="bank-registry-", suffix=".tmp", dir=str(self._path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, self._path)
            except Exception:
                try:
                    if os.path.exists(tmp_name):
                        os.remove(tmp_name)
                except OSError:
                    pass
                raise
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("保存词库登记表失败（%s），忽略本次保存", self._path)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @staticmethod
    def _record_from_dict(raw: Any) -> BankRecord | None:
        """逐字段容错构造记录；任一字段非法返回 ``None``。"""

        if not isinstance(raw, dict):
            return None
        bank_id = raw.get("id")
        name = raw.get("name")
        file_name = raw.get("file")
        added_at = raw.get("added_at")
        enabled = raw.get("enabled", True)
        if not all(isinstance(v, str) and v.strip() for v in (bank_id, name, file_name, added_at)):
            return None
        if not isinstance(enabled, bool):
            return None
        if "/" in file_name or "\\" in file_name or ".." in file_name:
            return None  # 文件名必须落在 banks/ 一级（防路径逃逸）
        return BankRecord(
            id=str(bank_id),
            name=str(name),
            file=str(file_name),
            enabled=enabled,
            added_at=str(added_at),
        )

    def _backup_corrupt(self, reason: str) -> None:
        """把损坏的登记表 ``os.replace`` 为 ``<name>.corrupt-<mtime>``（绝不覆盖旧备份）。"""

        try:
            if not self._path.exists():
                return
            try:
                suffix = str(int(os.stat(self._path).st_mtime))
            except OSError:
                suffix = "unknown"
            target = self._path.with_name(f"{self._path.name}.corrupt-{suffix}")
            counter = 1
            while target.exists():
                target = self._path.with_name(f"{self._path.name}.corrupt-{suffix}-{counter}")
                counter += 1
            os.replace(self._path, target)
            logger.warning("词库登记表损坏（%s）：%s 已备份为 %s", reason, self._path, target)
        except Exception:  # noqa: BLE001
            logger.exception("备份损坏的词库登记表失败（%s）", self._path)


__all__ = ["BankRecord", "BankInfo", "BankRegistryStore"]
