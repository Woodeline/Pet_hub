"""core.word_details_cache_store —— 用户级中文详情缓存（原子写 + 逐字段容错 + 损坏备份）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

设计要点（架构 §5.2 T02 / 共享知识「store 范式」）：
- 沿用本项目既有的原子写 + TTL 缓存设计（与 :class:`~desktop_pet.core.vocab_store.VocabStore`
  同构；刻意复制而非抽取共享工具，以免触碰既有测试）：
  - 读 = 逐字段容错（非法记录跳过、合法记录保留）。
  - 写 = ``tempfile.mkstemp`` 同目录 + ``flush/fsync`` + ``os.replace`` 原子替换。
  - 用户数据损坏 = 先 ``os.replace`` 备份为 ``<name>.corrupt-<mtime>`` 再以空缓存继续，
    **绝不静默清空**。
- ``fetched_at`` 由调用方（``app`` 层 ``_now_iso()``）注入；本模块**不解析时间戳**，
  TTL 判定在 app 层（``WORD_DETAILS_CACHE_TTL_DAYS=0`` ⇒ 永久有效）。
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
from desktop_pet.core.word_detail import WordDetail

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WordDetailsCacheItem:
    """一条中文详情缓存记录（抓取时间 + 详情快照）。"""

    fetched_at: str
    detail: WordDetail

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {"fetched_at": self.fetched_at, "detail": self.detail.to_dict()}

    @classmethod
    def from_dict(cls, data: Any) -> "WordDetailsCacheItem | None":
        """逐字段容错构造缓存记录；任一必填非法则返回 ``None``。"""

        if not isinstance(data, dict):
            return None
        fetched_at = data.get("fetched_at")
        if not isinstance(fetched_at, str) or not fetched_at.strip():
            return None
        detail = WordDetail.from_dict(data.get("detail"))
        if detail is None:
            return None
        return cls(fetched_at=fetched_at.strip(), detail=detail)


class WordDetailsCacheStore:
    """负责 ``word_details_cache.json`` 的容错读取、按词写入与原子保存。"""

    def __init__(self, path: Path) -> None:
        """创建中文详情缓存存储。

        Args:
            path: 缓存文件绝对路径。
        """

        self._path: Path = Path(path)
        self._items: dict[str, WordDetailsCacheItem] = {}

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    @property
    def path(self) -> Path:
        """缓存文件路径。"""

        return self._path

    @staticmethod
    def default_path() -> Path:
        """返回默认缓存路径 ``%APPDATA%\\desktop-pet\\word_details_cache.json``。

        ``APPDATA`` 不可用时回落到用户主目录，保证任何环境下都返回一个可写路径。
        """

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.WORD_DETAILS_CACHE_FILENAME

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def load(self) -> dict[str, WordDetailsCacheItem]:
        """容错加载缓存。

        - 文件缺失 / 为空 → 以空缓存启动（不备份）。
        - 结构损坏（JSON 解析失败 / 根非对象 / ``items`` 非对象）→ **先备份**再以空缓存继续。
        - 逐条非法记录跳过，保留合法记录。
        """

        try:
            if not self._path.exists():
                self._items = {}
                return {}
            text = self._path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("中文详情缓存文件为空：%s（以空缓存启动）", self._path)
                self._items = {}
                return {}

            data = json.loads(text)
            if not isinstance(data, dict):
                self._backup_corrupt("根节点不是对象")
                self._items = {}
                return {}

            raw_items = data.get("items")
            if not isinstance(raw_items, dict):
                self._backup_corrupt("items 字段不是对象")
                self._items = {}
                return {}

            items: dict[str, WordDetailsCacheItem] = {}
            skipped = 0
            for item_id, raw in raw_items.items():
                if not isinstance(item_id, str) or not item_id.strip():
                    skipped += 1
                    continue
                item = WordDetailsCacheItem.from_dict(raw)
                if item is None:
                    skipped += 1
                    continue
                items[item_id.strip()] = item

            if skipped:
                logger.warning("中文详情缓存 %s 中有 %d 条非法记录被跳过", self._path, skipped)

            self._items = items
            logger.info("中文详情缓存加载完成：%s（%d 条）", self._path, len(items))
            return dict(items)
        except json.JSONDecodeError as exc:
            self._backup_corrupt(f"JSON 解析失败：{exc}")
            self._items = {}
            return {}
        except OSError as exc:
            logger.warning("读取中文详情缓存失败（%s）：%s（以空缓存启动）", self._path, exc)
            self._items = {}
            return {}
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载中文详情缓存时发生未预期异常（%s），以空缓存启动", self._path)
            self._items = {}
            return {}

    # ------------------------------------------------------------------ #
    # 查询 / 写
    # ------------------------------------------------------------------ #
    def get(self, item_id: str) -> WordDetailsCacheItem | None:
        """按词条 ``id`` 返回缓存记录；不存在返回 ``None``。"""

        if not item_id:
            return None
        return self._items.get(item_id)

    def put(self, item_id: str, detail: WordDetail, fetched_at: str) -> None:
        """写入（或覆盖）一条缓存并落盘；空 ``id`` / ``None`` 详情忽略。"""

        if not item_id or detail is None:
            return
        self._items[str(item_id)] = WordDetailsCacheItem(
            fetched_at=str(fetched_at), detail=detail
        )
        self.save()

    def discard(self, item_id: str) -> bool:
        """按词条 ``id`` 删除一条缓存并落盘；``True`` = 已删除，``False`` = 不存在。

        词库纠错生效时使旧详情失效（释义 / 翻译变了，缓存的五要素不再可信），
        下次打开详情按「打包库 → 缓存 → 联网」重新解析。
        """

        if not item_id or str(item_id) not in self._items:
            return False
        del self._items[str(item_id)]
        self.save()
        return True

    def save(self) -> None:
        """原子保存缓存（``mkstemp`` + ``fsync`` + ``os.replace``）；失败仅记 warning。"""

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(
                {
                    "version": C.WORD_DETAILS_CACHE_VERSION,
                    "items": {key: item.to_dict() for key, item in self._items.items()},
                },
                ensure_ascii=False,
                indent=2,
            )
            fd, tmp_name = tempfile.mkstemp(
                prefix="word-details-cache-", suffix=".tmp", dir=str(self._path.parent)
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
            logger.info("中文详情缓存已保存：%s（%d 条）", self._path, len(self._items))
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("保存中文详情缓存失败（%s），忽略本次保存", self._path)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _backup_corrupt(self, reason: str) -> None:
        """把损坏的缓存 ``os.replace`` 为 ``<name>.corrupt-<时间戳>``（绝不覆盖旧备份）。"""

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
            logger.warning("中文详情缓存损坏（%s）：%s 已备份为 %s", reason, self._path, target)
        except Exception:  # noqa: BLE001 —— 备份失败也不能让程序崩溃
            logger.exception("备份损坏的中文详情缓存失败（%s）", self._path)

    def _corrupt_suffix(self) -> str:
        """生成备份文件名后缀（取损坏文件 mtime 的整数秒）。

        刻意**不 import** ``time`` / ``datetime``（core 时钟无关约定），
        改由 ``os.stat`` 读取文件自身的 mtime 作为确定性时间戳来源。
        """

        try:
            return str(int(os.stat(self._path).st_mtime))
        except OSError:
            return "unknown"


__all__ = ["WordDetailsCacheItem", "WordDetailsCacheStore"]
