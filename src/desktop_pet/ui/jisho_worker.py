"""ui.jisho_worker —— 把 ``core.jisho.fetch`` 放到 ``QThreadPool`` 后台线程执行。

线程边界（架构 §B8）：
- ``core.jisho`` 纯同步（**不开线程、不 import Qt/time**）。
- ``QThreadPool`` / ``QRunnable`` / ``QObject`` 信号只出现在 ``ui`` 层。
- ``JishoSignals`` 在主线程创建；``succeeded/failed`` 跨线程经 ``QueuedConnection`` 回主线程。
- 无结果时以 ``C.WORD_DETAIL_NOT_FOUND`` 作为 ``failed`` 的哨兵消息，供窗口显示「未找到」而非通用错误。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from desktop_pet.core import constants as C
from desktop_pet.core.jisho import JishoError, JishoNotFound, fetch

logger = logging.getLogger(__name__)


class JishoSignals(QObject):
    """Jisho 后台查询的回传信号（跨线程）。"""

    succeeded = Signal(str, object)  # (word, JishoResult)
    failed = Signal(str, str)        # (word, error_message)


class JishoWorker(QRunnable):
    """在后台线程执行一次 Jisho 查询。"""

    def __init__(self, word: str, timeout_s: float) -> None:
        """构造查询任务。

        Args:
            word: 待查询词条。
            timeout_s: 网络超时秒数。
        """

        super().__init__()
        self.word: str = word
        self.timeout_s: float = float(timeout_s)
        self.signals: JishoSignals = JishoSignals()

    def run(self) -> None:
        """执行查询并转 ``succeeded`` / ``failed`` 信号（绝不裸抛）。"""

        try:
            result = fetch(self.word, timeout_s=self.timeout_s)
        except JishoNotFound as exc:
            logger.info("Jisho 无结果（%s）：%s", self.word, exc)
            self.signals.failed.emit(self.word, C.WORD_DETAIL_NOT_FOUND)
        except JishoError as exc:
            logger.info("Jisho 查询失败（%s）：%s", self.word, exc)
            self.signals.failed.emit(self.word, str(exc))
        except Exception as exc:  # noqa: BLE001 —— 后台线程边界处绝不裸抛
            logger.exception("Jisho 查询未预期异常（%s）", self.word)
            self.signals.failed.emit(self.word, str(exc))
        else:
            self.signals.succeeded.emit(self.word, result)


__all__ = ["JishoSignals", "JishoWorker"]
