"""core.daily_log_store —— 每日学习记录持久化（原子写 + 逐字段容错读 + 损坏备份）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

JSON 结构：``{"version": 1, "days": {"YYYY-MM-DD": [DailyLogEntry, ...]}}``。

``day`` 是**调用方（app 层）注入的字符串 key**（本地自然日 ``YYYY-MM-DD``），
本模块只把它当普通字符串分桶，绝不解析、绝不自取时钟。``shown_at`` 由 app 注入
ISO8601 UTC 字符串。用户数据损坏时**绝不静默清空**（先备份 ``*.corrupt-*`` 再继续）。
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

#: 每日记录必填字段（均为非空 ``str``）
_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "level",
    "word",
    "kana",
    "translation",
    "shown_at",
    "status",
)


@dataclass(frozen=True)
class DailyLogEntry:
    """每日记录中的一条（词条冗余快照 + 展示时间 + 三态终态）。"""

    id: str
    level: str
    word: str
    kana: str
    translation: str
    shown_at: str
    status: str

    @classmethod
    def from_entry(cls, entry: VocabEntry, shown_at: str, status: str) -> "DailyLogEntry":
        """由词库词条 + 展示时间 + 终态构造记录。"""

        return cls(
            id=entry.id,
            level=entry.level,
            word=entry.word,
            kana=entry.kana,
            translation=entry.translation,
            shown_at=str(shown_at),
            status=str(status),
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {
            "id": self.id,
            "level": self.level,
            "word": self.word,
            "kana": self.kana,
            "translation": self.translation,
            "shown_at": self.shown_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "DailyLogEntry | None":
        """逐字段容错构造记录；任一必填非法或 ``status`` 越界则返回 ``None``。"""

        if not isinstance(data, dict):
            return None
        values: dict[str, str] = {}
        for key in _REQUIRED_FIELDS:
            raw = data.get(key)
            if not isinstance(raw, str) or not raw.strip():
                return None
            values[key] = raw.strip()

        if values["status"] not in C.DAILY_LOG_STATUSES:
            return None

        return cls(
            id=values["id"],
            level=values["level"],
            word=values["word"],
            kana=values["kana"],
            translation=values["translation"],
            shown_at=values["shown_at"],
            status=values["status"],
        )


class DailyLogStore:
    """负责 ``daily_log.json`` 的容错读取、按日分桶追加与原子保存。"""

    def __init__(self, path: Path) -> None:
        """创建每日记录存储。

        Args:
            path: 每日记录文件绝对路径。
        """

        self._path: Path = Path(path)
        self._days: dict[str, list[DailyLogEntry]] = {}

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    @property
    def path(self) -> Path:
        """每日记录文件路径。"""

        return self._path

    @staticmethod
    def default_path() -> Path:
        """返回默认路径 ``%APPDATA%\\desktop-pet\\daily_log.json``。

        ``APPDATA`` 不可用时回落到用户主目录，保证任何环境下都返回一个可写路径。
        """

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.DAILY_LOG_FILE_NAME

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def load(self) -> dict[str, list[DailyLogEntry]]:
        """容错加载每日记录。

        - 文件缺失 / 为空 → 以空表启动（不备份）。
        - 结构损坏（JSON 解析失败 / 根非对象 / ``days`` 非对象）→ **先备份**再以空表继续。
        - 单个 day 桶非数组 → 跳过该桶（保留其它合法桶）。
        - 逐条非法记录跳过，保留合法记录。
        """

        try:
            if not self._path.exists():
                self._days = {}
                return {}
            text = self._path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("每日记录文件为空：%s（以空表启动）", self._path)
                self._days = {}
                return {}

            data = json.loads(text)
            if not isinstance(data, dict):
                self._backup_corrupt("根节点不是对象")
                self._days = {}
                return {}

            raw_days = data.get("days")
            if not isinstance(raw_days, dict):
                self._backup_corrupt("days 字段不是对象")
                self._days = {}
                return {}

            days: dict[str, list[DailyLogEntry]] = {}
            skipped_buckets = 0
            skipped_entries = 0
            for day, raw_entries in raw_days.items():
                if not isinstance(day, str) or not isinstance(raw_entries, list):
                    skipped_buckets += 1
                    continue
                entries: list[DailyLogEntry] = []
                for raw in raw_entries:
                    entry = DailyLogEntry.from_dict(raw)
                    if entry is None:
                        skipped_entries += 1
                        continue
                    entries.append(entry)
                days[day] = entries

            if skipped_buckets:
                logger.warning("每日记录 %s 中有 %d 个非法日期桶被跳过", self._path, skipped_buckets)
            if skipped_entries:
                logger.warning("每日记录 %s 中有 %d 条非法记录被跳过", self._path, skipped_entries)

            self._days = days
            logger.info("每日记录加载完成：%s（%d 天）", self._path, len(days))
            return dict(days)
        except json.JSONDecodeError as exc:
            self._backup_corrupt(f"JSON 解析失败：{exc}")
            self._days = {}
            return {}
        except OSError as exc:
            logger.warning("读取每日记录失败（%s）：%s（以空表启动）", self._path, exc)
            self._days = {}
            return {}
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载每日记录时发生未预期异常（%s），以空表启动", self._path)
            self._days = {}
            return {}

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def days(self) -> list[str]:
        """返回全部日期 key，降序（最新在前，供回查下拉）。"""

        return sorted(self._days.keys(), reverse=True)

    def entries_for(self, day: str) -> list[DailyLogEntry]:
        """返回指定日期的记录（按插入顺序）；无记录返回空列表。"""

        return list(self._days.get(str(day), []))

    def count_for(self, day: str) -> int:
        """返回指定日期的记录总数（= 当日已展示且已处置的词条数）。"""

        return len(self._days.get(str(day), []))

    def new_word_count_for(self, day: str) -> int:
        """返回指定日期的**新词**展示数（排除复习两态）。

        每日数量配额的语义是「新词学习量」：复习处置（``review_ok`` /
        ``review_lapsed``）虽写入每日记录留痕，但不占用新词配额——
        否则复习多的日子会挤掉新词学习（记忆曲线的复习是刚性约定）。
        """

        review_statuses = (C.DAILY_LOG_STATUS_REVIEW_OK, C.DAILY_LOG_STATUS_REVIEW_LAPSED)
        return sum(
            1
            for entry in self._days.get(str(day), [])
            if entry.status not in review_statuses
        )

    def review_count_for(self, day: str) -> int:
        """返回指定日期已**作答**的复习轮数（记得 + 忘了）。

        每日复习上限的计数口径：只数真实作答（消耗用户注意力的复习）；
        超时顺延不算——没作答的复习没有消耗，不应烧掉额度。
        """

        return self._count_status(day, C.DAILY_LOG_STATUS_REVIEW_OK) + self._count_status(
            day, C.DAILY_LOG_STATUS_REVIEW_LAPSED
        )

    def mastered_count_for(self, day: str) -> int:
        """返回指定日期「已掌握」条数。"""

        return self._count_status(day, C.DAILY_LOG_STATUS_MASTERED)

    def vocab_count_for(self, day: str) -> int:
        """返回指定日期「生词」条数。"""

        return self._count_status(day, C.DAILY_LOG_STATUS_VOCAB)

    def unprocessed_count_for(self, day: str) -> int:
        """返回指定日期「未处理」条数。"""

        return self._count_status(day, C.DAILY_LOG_STATUS_UNPROCESSED)

    def shown_ids_for(self, day: str) -> set[str]:
        """返回指定日期已展示（已处置）词条的 id 集合，供当日抽取排除。"""

        return {entry.id for entry in self._days.get(str(day), [])}

    def all_mastered(self, day: str) -> bool:
        """当日「已展示 > 0 且 已掌握 == 已展示」，即所有展示词均已标记掌握。

        注意：该方法已**不再用于停止判定**（``_jp_stop_for_today`` 只按每日上限判断）。
        它曾被误用于「当日全部掌握即早停」，导致用户对第一个词点「记住了」就误触发
        （count==mastered_count），当天后续单词全部停摆。保留本方法仅为既有调用方
        （学习记录窗口状态栏展示）与兼容性，不再承载业务停止语义。
        """

        count = self.count_for(day)
        return count > 0 and self.mastered_count_for(day) == count

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def add_entry(self, day: str, entry: DailyLogEntry) -> None:
        """把一条记录 append 到指定日期桶并落盘。"""

        if entry is None:
            return
        key = str(day)
        self._days.setdefault(key, []).append(entry)
        self.save()

    def save(self) -> None:
        """原子保存（``mkstemp`` + ``fsync`` + ``os.replace``）；失败仅记 warning。"""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "version": C.DAILY_LOG_VERSION,
                    "days": {
                        day: [entry.to_dict() for entry in entries]
                        for day, entries in self._days.items()
                    },
                },
                ensure_ascii=False,
                indent=2,
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix="daily-log-", suffix=".tmp", dir=str(self._path.parent)
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
            logger.info("每日记录已保存：%s（%d 天）", self._path, len(self._days))
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("保存每日记录失败（%s），忽略本次保存", self._path)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _count_status(self, day: str, status: str) -> int:
        """返回指定日期桶内 ``status`` 匹配的记录数。"""

        return sum(1 for entry in self._days.get(str(day), []) if entry.status == status)

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
            logger.warning("每日记录损坏（%s）：%s 已备份为 %s", reason, self._path, target)
        except Exception:  # noqa: BLE001 —— 备份失败也不能让程序崩溃
            logger.exception("备份损坏的每日记录失败（%s）", self._path)

    def _corrupt_suffix(self) -> str:
        """生成备份文件名后缀（取损坏文件 mtime 的整数秒）。

        刻意**不 import** ``time`` / ``datetime``（core 时钟无关约定），
        改由 ``os.stat`` 读取文件自身的 mtime 作为确定性时间戳来源。
        """

        try:
            return str(int(os.stat(self._path).st_mtime))
        except OSError:
            return "unknown"


__all__ = ["DailyLogEntry", "DailyLogStore"]
