"""ui.update_worker —— 把 ``core.update_client`` 的同步查询放到 ``QThreadPool`` 后台线程。

线程边界与 ``ui.word_detail_worker`` 完全同构：
- ``core.update_client`` 纯同步（**不开线程、不 import Qt/time**）。
- ``QThreadPool`` / ``QRunnable`` / ``QObject`` 信号只出现在 ``ui`` 层。
- ``UpdateCheckSignals`` 在主线程创建；``succeeded/failed`` 跨线程经
  ``QueuedConnection`` 回主线程。
- ``run()`` 内**绝不裸抛**：``UpdateCheckError`` 与兜底 ``Exception`` 一律转 ``failed``。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QRunnable, Signal

from desktop_pet.core.update_client import ReleaseInfo, UpdateCheckError, fetch_latest_release

logger = logging.getLogger(__name__)


class UpdateCheckSignals(QObject):
    """更新检查的回传信号（跨线程）。"""

    succeeded = Signal(object)  # ReleaseInfo
    failed = Signal(str)        # error_message（用户可读）


class UpdateCheckWorker(QRunnable):
    """在后台线程执行一次「最新 Release」查询。"""

    def __init__(self, timeout_s: float) -> None:
        """构造查询任务。

        Args:
            timeout_s: HTTP 超时（秒；由 app 层从配置现取）。
        """

        super().__init__()
        self._timeout_s: float = float(timeout_s)
        self.signals: UpdateCheckSignals = UpdateCheckSignals()

    def run(self) -> None:
        """执行查询并转 ``succeeded`` / ``failed`` 信号（绝不裸抛）。"""

        try:
            release = fetch_latest_release(timeout_s=self._timeout_s)
        except UpdateCheckError as exc:
            logger.info("检查更新失败：%s", exc)
            self.signals.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001 —— 后台线程边界处绝不裸抛
            logger.exception("检查更新未预期异常")
            self.signals.failed.emit(str(exc))
        else:
            self.signals.succeeded.emit(release)


__all__ = ["UpdateCheckSignals", "UpdateCheckWorker"]
