"""core.mastered_store —— 已掌握单词集合 + 记忆曲线（间隔重复）状态持久化。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

范式与 :class:`~desktop_pet.core.vocab_store.VocabStore` 完全同构（**刻意复制，不抽取共享工具**，
以避免触碰既有测试）：
- 用户数据损坏时**绝不静默清空**：先把损坏文件 ``os.replace`` 备份为
  ``<name>.corrupt-<时间戳>`` 再以空集合继续运行（数据由备份保全）。
- 保存采用「``tempfile.mkstemp`` 同目录 + ``flush/fsync`` + ``os.replace`` 原子替换」。
- 所有时间字符串（``mastered_at`` / ``due_at`` / ``last_review_at``）由调用方（``app`` 层）
  注入 ISO8601 UTC 字符串（``%Y-%m-%dT%H:%M:%SZ`` 定长零填充格式）；本模块**不解析时间戳**，
  仅按**插入顺序**排序、按**字典序**比较到期——定长 UTC 格式的字典序即时间序（不变式由
  app 层注入格式保证）。

记忆曲线（间隔重复，v2 新增）：
- 每条记录携带 ``stage``（下一轮复习的间隔下标）/ ``due_at``（下次复习到期时刻）/
  ``last_review_at`` / ``review_count``；间隔阶梯见 :data:`~desktop_pet.core.constants.REVIEW_INTERVALS_DAYS`。
- 阶段推进与到期换算（日期算术）由 **app 层**完成：本模块只存取字段；
  ``apply_review`` / ``set_due_at`` 的入参就是算好的 stage 与 due_at。
- v1 记录（无 SRS 字段）逐字段容错读入：``stage=0`` / ``due_at=""``（由 app 层启动迁移补排期）。
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

#: 已掌握记录必填字段（均为非空 ``str``）
_REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "level",
    "word",
    "kana",
    "translation",
    "mastered_at",
)
#: ``stage`` 达到该值 = 毕业（间隔阶梯走完，不再排期复习）
_MAX_STAGE: int = len(C.REVIEW_INTERVALS_DAYS)


@dataclass(frozen=True)
class MasteredItem:
    """已掌握单词集合中的一条记录（词条冗余快照 + 掌握时间 + SRS 状态）。"""

    id: str
    level: str
    word: str
    kana: str
    translation: str
    mastered_at: str
    #: 下一轮复习使用的间隔下标（0 起；== ``len(REVIEW_INTERVALS_DAYS)`` 表示已毕业）
    stage: int = 0
    #: 下次复习到期时刻（ISO8601 UTC 定长字符串；``""`` = 未排期 / 已毕业）
    due_at: str = ""
    #: 最近一次复习时间（掌握瞬间 = ``mastered_at``；空 = 尚未复习过）
    last_review_at: str = ""
    #: 已完成的复习轮数（不含掌握本身）
    review_count: int = 0

    @classmethod
    def from_entry(
        cls,
        entry: VocabEntry,
        mastered_at: str,
        *,
        stage: int = 0,
        due_at: str = "",
    ) -> "MasteredItem":
        """由词库词条 + 掌握时间构造已掌握记录（SRS 初态：stage=0，到期由 app 注入）。"""

        return cls(
            id=entry.id,
            level=entry.level,
            word=entry.word,
            kana=entry.kana,
            translation=entry.translation,
            mastered_at=str(mastered_at),
            stage=int(stage),
            due_at=str(due_at or ""),
            last_review_at=str(mastered_at),
            review_count=0,
        )

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {
            "id": self.id,
            "level": self.level,
            "word": self.word,
            "kana": self.kana,
            "translation": self.translation,
            "mastered_at": self.mastered_at,
            "stage": self.stage,
            "due_at": self.due_at,
            "last_review_at": self.last_review_at,
            "review_count": self.review_count,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "MasteredItem | None":
        """逐字段容错构造记录；任一必填非法则返回 ``None``（逐条跳过，保留合法记录）。

        v2 SRS 字段容错缺省：``stage`` 非法（越界 / 非整数）→ 0；``due_at`` /
        ``last_review_at`` 缺失或非法 → ``""``；``review_count`` 非法 → 0。
        """

        if not isinstance(data, dict):
            return None
        values: dict[str, str] = {}
        for key in _REQUIRED_FIELDS:
            raw = data.get(key)
            if not isinstance(raw, str) or not raw.strip():
                return None
            values[key] = raw.strip()

        stage_raw = data.get("stage")
        stage = (
            int(stage_raw)
            if isinstance(stage_raw, int)
            and not isinstance(stage_raw, bool)
            and 0 <= stage_raw <= _MAX_STAGE
            else 0
        )
        due_raw = data.get("due_at")
        due_at = due_raw.strip() if isinstance(due_raw, str) else ""
        last_raw = data.get("last_review_at")
        last_review_at = last_raw.strip() if isinstance(last_raw, str) else ""
        count_raw = data.get("review_count")
        review_count = (
            int(count_raw)
            if isinstance(count_raw, int) and not isinstance(count_raw, bool) and count_raw >= 0
            else 0
        )

        return cls(
            id=values["id"],
            level=values["level"],
            word=values["word"],
            kana=values["kana"],
            translation=values["translation"],
            mastered_at=values["mastered_at"],
            stage=stage,
            due_at=due_at,
            last_review_at=last_review_at,
            review_count=review_count,
        )


class MasteredStore:
    """负责 ``mastered.json`` 的容错读取、按 id 去重追加与原子保存。"""

    def __init__(self, path: Path) -> None:
        """创建已掌握集合存储。

        Args:
            path: 已掌握集合文件绝对路径。
        """

        self._path: Path = Path(path)
        self._items: list[MasteredItem] = []

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    @property
    def path(self) -> Path:
        """已掌握集合文件路径。"""

        return self._path

    @staticmethod
    def default_path() -> Path:
        """返回默认路径 ``%APPDATA%\\desktop-pet\\mastered.json``。

        ``APPDATA`` 不可用时回落到用户主目录，保证任何环境下都返回一个可写路径。
        """

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.MASTERED_FILE_NAME

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def load(self) -> list[MasteredItem]:
        """容错加载已掌握集合。

        - 文件缺失 / 为空 → 以空集合启动（不备份）。
        - 结构损坏（JSON 解析失败 / 根非对象 / ``items`` 非数组）→ **先备份**再以空集合继续。
        - 逐条非法记录跳过，保留合法记录。
        """

        try:
            if not self._path.exists():
                self._items = []
                return []
            text = self._path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("已掌握集合文件为空：%s（以空集合启动）", self._path)
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

            items: list[MasteredItem] = []
            skipped = 0
            for raw in raw_items:
                item = MasteredItem.from_dict(raw)
                if item is None:
                    skipped += 1
                    continue
                items.append(item)

            if skipped:
                logger.warning("已掌握集合 %s 中有 %d 条非法记录被跳过", self._path, skipped)

            self._items = items
            logger.info("已掌握集合加载完成：%s（%d 条）", self._path, len(items))
            return list(items)
        except json.JSONDecodeError as exc:
            self._backup_corrupt(f"JSON 解析失败：{exc}")
            self._items = []
            return []
        except OSError as exc:
            logger.warning("读取已掌握集合失败（%s）：%s（以空集合启动）", self._path, exc)
            self._items = []
            return []
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载已掌握集合时发生未预期异常（%s），以空集合启动", self._path)
            self._items = []
            return []

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def items(self) -> list[MasteredItem]:
        """返回内部记录列表（按加入顺序）。"""

        return self._items

    def ids(self) -> set[str]:
        """返回全部已掌握词条 id 集合（供抽取排除用）。"""

        return {item.id for item in self._items}

    def contains(self, item_id: str) -> bool:
        """返回是否已掌握指定 ``id``。"""

        return any(item.id == item_id for item in self._items)

    def count(self) -> int:
        """返回已掌握数量。"""

        return len(self._items)

    def get(self, item_id: str) -> "MasteredItem | None":
        """按 ``id`` 取一条记录；不存在返回 ``None``。"""

        for item in self._items:
            if item.id == str(item_id):
                return item
        return None

    # ------------------------------------------------------------------ #
    # 记忆曲线：到期查询（字典序比较，不变式见模块 docstring）
    # ------------------------------------------------------------------ #
    def due_items(self, now_iso: str) -> list["MasteredItem"]:
        """返回已到期（``due_at <= now_iso``）且未毕业的记录，按到期时刻升序。

        Args:
            now_iso: 当前时刻（ISO8601 UTC 定长字符串，由 app 层注入）。

        Returns:
            到期记录列表（最早到期的在前）；无到期返回空列表。
        """

        now = str(now_iso)
        due = [
            item
            for item in self._items
            if item.due_at and item.stage < _MAX_STAGE and item.due_at <= now
        ]
        due.sort(key=lambda item: item.due_at)
        return due

    def earliest_due_iso(self) -> str:
        """返回最早的未毕业 ``due_at``（含未来时刻）；无排期返回 ``""``。"""

        candidates = [
            item.due_at for item in self._items if item.due_at and item.stage < _MAX_STAGE
        ]
        return min(candidates) if candidates else ""

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def add(
        self,
        entry: VocabEntry,
        mastered_at: str,
        *,
        stage: int = 0,
        due_at: str = "",
    ) -> bool:
        """按 ``id`` 去重追加一条；``True`` = 新增，``False`` = 已存在 / 非法。

        Args:
            entry: 词库词条。
            mastered_at: 掌握时间（ISO8601 UTC，app 层注入）。
            stage: SRS 初态阶段（默认 0 = 首轮间隔）。
            due_at: 首轮复习到期时刻（ISO8601 UTC，app 层算好注入；空 = 未排期）。
        """

        if entry is None or not getattr(entry, "id", ""):
            return False
        if self.contains(entry.id):
            return False
        self._items.append(
            MasteredItem.from_entry(entry, str(mastered_at), stage=stage, due_at=due_at)
        )
        self.save()
        return True

    def apply_review(
        self, item_id: str, *, stage: int, due_at: str, reviewed_at: str
    ) -> bool:
        """记录一轮复习结果（阶段推进 / 毕业 / 顺延均经此落盘）。

        Args:
            item_id: 词条 id。
            stage: 新阶段（app 层按阶梯算好；毕业时 = ``len(REVIEW_INTERVALS_DAYS)``）。
            due_at: 新到期时刻（毕业时传 ``""``）。
            reviewed_at: 本次复习时间（写入 ``last_review_at``，``review_count`` +1）。

        Returns:
            ``True`` = 已更新；``False`` = 记录不存在。
        """

        for index, item in enumerate(self._items):
            if item.id == str(item_id):
                self._items[index] = MasteredItem(
                    id=item.id,
                    level=item.level,
                    word=item.word,
                    kana=item.kana,
                    translation=item.translation,
                    mastered_at=item.mastered_at,
                    stage=int(stage),
                    due_at=str(due_at or ""),
                    last_review_at=str(reviewed_at),
                    review_count=item.review_count + 1,
                )
                self.save()
                return True
        return False

    def set_due_at(self, item_id: str, due_at: str) -> bool:
        """仅改到期时刻（超时顺延 / 启动迁移补排期）；不推进阶段、不计复习次数。"""

        for index, item in enumerate(self._items):
            if item.id == str(item_id):
                self._items[index] = MasteredItem(
                    id=item.id,
                    level=item.level,
                    word=item.word,
                    kana=item.kana,
                    translation=item.translation,
                    mastered_at=item.mastered_at,
                    stage=item.stage,
                    due_at=str(due_at or ""),
                    last_review_at=item.last_review_at,
                    review_count=item.review_count,
                )
                self.save()
                return True
        return False

    def remove(self, item_id: str) -> bool:
        """按 ``id`` 删除一条（撤销误标）；``True`` = 已删除，``False`` = 不存在。"""

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
        """原子保存（``mkstemp`` + ``fsync`` + ``os.replace``）；失败仅记 warning。"""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {"version": C.MASTERED_VERSION, "items": [item.to_dict() for item in self._items]},
                ensure_ascii=False,
                indent=2,
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix="mastered-", suffix=".tmp", dir=str(self._path.parent)
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
            logger.info("已掌握集合已保存：%s（%d 条）", self._path, len(self._items))
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("保存已掌握集合失败（%s），忽略本次保存", self._path)

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
            logger.warning("已掌握集合损坏（%s）：%s 已备份为 %s", reason, self._path, target)
        except Exception:  # noqa: BLE001 —— 备份失败也不能让程序崩溃
            logger.exception("备份损坏的已掌握集合失败（%s）", self._path)

    def _corrupt_suffix(self) -> str:
        """生成备份文件名后缀（取损坏文件 mtime 的整数秒）。

        刻意**不 import** ``time`` / ``datetime``（core 时钟无关约定），
        改由 ``os.stat`` 读取文件自身的 mtime 作为确定性时间戳来源。
        """

        try:
            return str(int(os.stat(self._path).st_mtime))
        except OSError:
            return "unknown"


__all__ = ["MasteredItem", "MasteredStore"]
