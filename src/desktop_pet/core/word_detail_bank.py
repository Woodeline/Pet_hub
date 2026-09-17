"""core.word_detail_bank —— 打包内置中文详情库的只读加载器（纯读，零 Qt 零 time）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

文件契约（键为词条 ``id``）::

    {"version": 1, "details": {"n5-0001": {五要素}}}

加载容错（架构 §5.2 T02）：文件缺失 / 为空 / 根非对象 / ``details`` 非对象 /
逐条非法 → 优雅降级；**仅记 ``logger.warning``，绝不抛异常**。
本库为**权威只读版本**，运行期不写回（用户联网结果写入独立的用户缓存）。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from desktop_pet.core.word_detail import WordDetail

logger = logging.getLogger(__name__)

#: 详情库中承载「id → 五要素」的字段名
_DETAILS_KEY: str = "details"


class WordDetailBank:
    """只读中文详情库：按词条 ``id`` 提供详情查询。"""

    def __init__(self, details: dict[str, WordDetail]) -> None:
        """以给定映射构造详情库（一般经 :meth:`load` / :meth:`empty` 创建）。"""

        self._details: dict[str, WordDetail] = dict(details)

    # ------------------------------------------------------------------ #
    # 构造
    # ------------------------------------------------------------------ #
    @classmethod
    def load(cls, path: Path) -> "WordDetailBank":
        """从 JSON 文件容错加载详情库。

        文件缺失 / 解析失败 / 根非对象 / ``details`` 非对象 → 返回空库，
        仅记 ``logger.warning``，绝不抛异常。逐条非法记录跳过。
        """

        try:
            bank_path = Path(path)
            if not bank_path.exists():
                logger.warning("详情库文件不存在：%s（使用空详情库）", bank_path)
                return cls.empty()

            text = bank_path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("详情库文件为空：%s（使用空详情库）", bank_path)
                return cls.empty()

            data = json.loads(text)
            if not isinstance(data, dict):
                logger.warning("详情库根节点不是对象：%s（使用空详情库）", bank_path)
                return cls.empty()

            raw_details = data.get(_DETAILS_KEY)
            if not isinstance(raw_details, dict):
                logger.warning("详情库 details 字段不是对象：%s（使用空详情库）", bank_path)
                return cls.empty()

            details: dict[str, WordDetail] = {}
            skipped = 0
            for key, raw in raw_details.items():
                if not isinstance(key, str) or not key.strip():
                    skipped += 1
                    continue
                detail = WordDetail.from_dict(raw)
                if detail is None:
                    skipped += 1
                    continue
                details[key.strip()] = detail

            if skipped:
                logger.warning("详情库 %s 中有 %d 条非法记录被跳过", bank_path, skipped)

            logger.info("详情库加载完成：%s（%d 条）", bank_path, len(details))
            return cls(details)
        except json.JSONDecodeError as exc:
            logger.warning("详情库 JSON 解析失败（%s）：%s（使用空详情库）", path, exc)
        except OSError as exc:
            logger.warning("读取详情库失败（%s）：%s（使用空详情库）", path, exc)
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("加载详情库时发生未预期异常（%s），使用空详情库", path)
        return cls.empty()

    @classmethod
    def empty(cls) -> "WordDetailBank":
        """返回空详情库。"""

        return cls({})

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def get(self, item_id: str) -> WordDetail | None:
        """按词条 ``id`` 返回详情；未命中或内容为空返回 ``None``。"""

        if not item_id:
            return None
        detail = self._details.get(item_id)
        if detail is None or detail.is_empty():
            return None
        return detail

    def size(self) -> int:
        """返回已收录词条数量（含空内容条目）。"""

        return len(self._details)

    def is_empty(self) -> bool:
        """返回详情库是否为空（无任何条目）。"""

        return not self._details


__all__ = ["WordDetailBank"]
