"""core.jp_state —— 日语学习进度持久化（已记住集合 + 每日展示进度）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

职责（JP-18/19）：
- ``learned_ids``：被标记「记住了」的词条 id 全集，**跨天永久保留**，之后不再出现。
- ``shown_ids``：当天已展示过的词条 id（去重），用于每日配额判定与
  「当天全部标记记住即停」判定；**跨天自动清零**（rollover）。
- ``date``：进度归属日期（ISO ``YYYY-MM-DD``），由调用方（app 层）注入"今天"，
  本模块不获取时钟；日期为纯字符串比较（ISO 格式字典序即时间序）。

容错（与 :class:`~desktop_pet.core.vocab_store.VocabStore` 同构）：
- 文件缺失 / 为空 → 以空进度启动（不备份）。
- 结构损坏 → 先备份为 ``<name>.corrupt-<mtime秒>`` 再以空进度继续（数据由备份保全）。
- 保存走「同目录 ``mkstemp`` + ``flush/fsync`` + ``os.replace``」原子替换。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)


class JpStateStore:
    """负责 ``jp_state.json`` 的容错读取、跨天 rollover 与原子保存。"""

    def __init__(self, path: Path) -> None:
        """创建进度存储。

        Args:
            path: 进度文件绝对路径。
        """

        self._path: Path = Path(path)
        self._date: str = ""
        self._shown_ids: list[str] = []
        self._learned_ids: set[str] = set()

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    @property
    def path(self) -> Path:
        """进度文件路径。"""

        return self._path

    @staticmethod
    def default_path() -> Path:
        """返回默认进度路径 ``%APPDATA%\\desktop-pet\\jp_state.json``。

        ``APPDATA`` 不可用时回落到用户主目录，保证任何环境下都返回一个可写路径。
        """

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.JP_STATE_FILE_NAME

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def load(self, today: str) -> None:
        """容错加载进度，并把归属日期收敛到 ``today``（必要时 rollover）。

        Args:
            today: 当天日期（ISO ``YYYY-MM-DD``，由 app 层注入）。
        """

        self._date = ""
        self._shown_ids = []
        self._learned_ids = set()

        try:
            if not self._path.exists():
                self._rollover_in_memory(today)
                return
            text = self._path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("学习进度文件为空：%s（以空进度启动）", self._path)
                self._rollover_in_memory(today)
                return

            data = json.loads(text)
            if not isinstance(data, dict):
                self._backup_corrupt("根节点不是对象")
                self._rollover_in_memory(today)
                return

            date = data.get("date")
            raw_shown = data.get("shown_ids")
            raw_learned = data.get("learned_ids")
            if not isinstance(date, str) or not isinstance(raw_shown, list) or not isinstance(raw_learned, list):
                self._backup_corrupt("字段结构非法")
                self._rollover_in_memory(today)
                return

            shown = [str(item).strip() for item in raw_shown if isinstance(item, str) and item.strip()]
            learned = {str(item).strip() for item in raw_learned if isinstance(item, str) and item.strip()}
            self._date = date
            self._shown_ids = shown
            self._learned_ids = learned
            self.rollover(today)  # 跨天则清当日进度（learned 保留）
            logger.info(
                "学习进度加载完成：%s（date=%s 当日已展示 %d 个，累计已记住 %d 个）",
                self._path, self._date, len(self._shown_ids), len(self._learned_ids),
            )
        except json.JSONDecodeError as exc:
            self._backup_corrupt(f"JSON 解析失败：{exc}")
            self._rollover_in_memory(today)
        except OSError as exc:
            logger.warning("读取学习进度失败（%s）：%s（以空进度启动）", self._path, exc)
            self._rollover_in_memory(today)
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载学习进度时发生未预期异常（%s），以空进度启动", self._path)
            self._rollover_in_memory(today)

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def date(self) -> str:
        """当前进度归属日期。"""

        return self._date

    def shown_ids(self) -> list[str]:
        """当天已展示过的词条 id（去重，按首次展示顺序）。"""

        return list(self._shown_ids)

    def learned_ids(self) -> set[str]:
        """已记住词条 id 全集（跨天永久）。"""

        return set(self._learned_ids)

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def rollover(self, today: str) -> None:
        """若归属日期不是 ``today``，清空当日进度（learned 保留）并落盘。"""

        if self._date == today:
            return
        self._rollover_in_memory(today)
        self.save()

    def record_shown(self, entry_id: str, today: str) -> None:
        """记录一条当日展示（去重，空白 id 忽略）；必要时先 rollover。"""

        entry_id = str(entry_id).strip()
        if not entry_id:
            return
        self.rollover(today)
        if entry_id not in self._shown_ids:
            self._shown_ids.append(entry_id)
        self.save()

    def record_learned(self, entry_id: str, today: str) -> None:
        """把词条标记为「已记住」（跨天永久，空白 id 忽略）；必要时先 rollover。"""

        entry_id = str(entry_id).strip()
        if not entry_id:
            return
        self.rollover(today)
        self._learned_ids.add(entry_id)
        self.save()

    def save(self) -> None:
        """原子保存进度（``mkstemp`` + ``fsync`` + ``os.replace``）；失败仅记 warning。"""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "version": C.JP_STATE_VERSION,
                    "date": self._date,
                    "shown_ids": list(self._shown_ids),
                    "learned_ids": sorted(self._learned_ids),
                },
                ensure_ascii=False,
                indent=2,
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix="jpstate-", suffix=".tmp", dir=str(self._path.parent)
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
            logger.debug("学习进度已保存：%s（date=%s）", self._path, self._date)
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("保存学习进度失败（%s），忽略本次保存", self._path)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _rollover_in_memory(self, today: str) -> None:
        """仅在内存中完成跨天清零（不落盘，由随后的 save 持久化）。"""

        self._date = str(today)
        self._shown_ids = []

    def _backup_corrupt(self, reason: str) -> None:
        """把损坏的进度文件 ``os.replace`` 为 ``<name>.corrupt-<时间戳>``（绝不覆盖旧备份）。"""

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
            logger.warning("学习进度损坏（%s）：%s 已备份为 %s", reason, self._path, target)
        except Exception:  # noqa: BLE001 —— 备份失败也不能让程序崩溃
            logger.exception("备份损坏的学习进度失败（%s）", self._path)

    def _corrupt_suffix(self) -> str:
        """生成备份文件名后缀（取损坏文件 mtime 的整数秒；不 import time/datetime）。"""

        try:
            return str(int(os.stat(self._path).st_mtime))
        except OSError:
            return "unknown"


__all__ = ["JpStateStore"]
