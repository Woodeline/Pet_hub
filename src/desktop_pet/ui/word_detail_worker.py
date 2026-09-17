"""ui.word_detail_worker —— 把 ``core.llm_client`` 的同步查询放到 ``QThreadPool`` 后台线程。

线程边界（架构 §5.2 T03 / 共享知识）：
- ``core.llm_client`` 纯同步（**不开线程、不 import Qt/time**）。
- ``QThreadPool`` / ``QRunnable`` / ``QObject`` 信号只出现在 ``ui`` 层。
- ``WordDetailSignals`` 在主线程创建；``succeeded/failed`` 跨线程经 ``QueuedConnection`` 回主线程。
- ``run()`` 内**绝不裸抛**：``LLMError`` 与兜底 ``Exception`` 一律转 ``failed`` 信号。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from PySide6.QtCore import QObject, QRunnable, Signal

from desktop_pet.core.llm_client import DeepSeekClient, LLMError
from desktop_pet.core.word_detail import WordDetail

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WordDetailNetConfig:
    """联网配置快照（由 ``app`` 层从当前 :class:`AppConfig` 现取现构）。"""

    api_key: str
    base_url: str
    model: str
    timeout_s: float
    retries: int


class WordDetailSignals(QObject):
    """详情联网查询的回传信号（跨线程）。"""

    succeeded = Signal(str, object)  # (item_id, WordDetail)
    failed = Signal(str, str)        # (item_id, error_message)


class WordDetailWorker(QRunnable):
    """在后台线程执行一次中文详情联网查询。"""

    def __init__(
        self,
        item_id: str,
        word: str,
        kana: str,
        level: str,
        translation: str,
        net: WordDetailNetConfig,
    ) -> None:
        """构造查询任务。

        Args:
            item_id: 词条唯一 id（用于回传定位）。
            word: 日语单词。
            kana: 假名读音。
            level: JLPT 等级。
            translation: 参考中文词义。
            net: 联网配置。
        """

        super().__init__()
        self.item_id: str = str(item_id)
        self.word: str = str(word)
        self.kana: str = str(kana or "")
        self.level: str = str(level or "")
        self.translation: str = str(translation or "")
        self.net: WordDetailNetConfig = net
        self.signals: WordDetailSignals = WordDetailSignals()

    def run(self) -> None:
        """执行查询并转 ``succeeded`` / ``failed`` 信号（绝不裸抛）。"""

        if self.net is None:
            self.signals.failed.emit(self.item_id, "未配置联网参数")
            return
        try:
            client = DeepSeekClient(
                api_key=self.net.api_key,
                base_url=self.net.base_url,
                model=self.net.model,
                timeout_s=self.net.timeout_s,
                retries=self.net.retries,
            )
            detail: WordDetail = client.fetch_word_detail(
                self.word, self.kana, self.level, self.translation
            )
        except LLMError as exc:
            logger.info("详情联网失败（%s）：%s", self.word, exc)
            self.signals.failed.emit(self.item_id, str(exc))
        except Exception as exc:  # noqa: BLE001 —— 后台线程边界处绝不裸抛
            logger.exception("详情联网未预期异常（%s）", self.word)
            self.signals.failed.emit(self.item_id, str(exc))
        else:
            self.signals.succeeded.emit(self.item_id, detail)


__all__ = ["WordDetailNetConfig", "WordDetailSignals", "WordDetailWorker"]
