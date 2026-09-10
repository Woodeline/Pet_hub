"""app.keyboard_listener —— pynput 守护线程 + Qt 跨线程信号桥（FR-01 / FR-24）。

线程模型（架构 §9.7）：
- ``pynput.keyboard.Listener`` 运行在**独立守护线程**。
- 回调 ``_on_press`` **只做一件事**：``bridge.emit_keystroke(ts)``，
  **绝不触碰任何 Qt widget**。跨线程由 Qt ``AutoConnection`` 自动排队投递到主线程。
- 任何异常都被捕获并记日志，**绝不让程序崩溃**。
- ``stop()`` 确保监听线程真正退出，无残留线程（FR-24）。
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


class KeystrokeBridge(QObject):
    """跨线程信号桥：把工作线程的按键事件安全投递到主线程。"""

    #: 携带按键时刻（秒，``time.monotonic()``）
    keystroke = Signal(float)

    def __init__(self, parent: QObject | None = None) -> None:
        """构造信号桥。"""

        super().__init__(parent)

    def emit_keystroke(self, timestamp: float) -> None:
        """发出一次按键信号（工作线程调用，线程安全）。

        Args:
            timestamp: 按键时刻（秒）。
        """

        self.keystroke.emit(float(timestamp))


class KeyboardListener:
    """全局键盘监听封装（pynput 守护线程）。"""

    def __init__(self, bridge: KeystrokeBridge) -> None:
        """构造监听器。

        Args:
            bridge: 负责把事件投递到主线程的信号桥。
        """

        self._bridge: KeystrokeBridge = bridge
        self._listener: Optional[Any] = None
        self._running: bool = False
        self._lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """启动监听（幂等；失败只记日志，不抛出）。"""

        with self._lock:
            if self._running:
                logger.debug("键盘监听已在运行，忽略重复启动")
                return
            try:
                # 延迟导入，避免在 core/ui 未就绪时引入平台钩子
                from pynput import keyboard  # type: ignore[import-untyped]

                listener = keyboard.Listener(on_press=self._on_press)
                listener.daemon = True
                listener.start()
                self._listener = listener
                self._running = True
                logger.info("全局键盘监听已启动")
            except Exception:  # noqa: BLE001 —— FR-01：监听失败不崩溃
                logger.exception("启动全局键盘监听失败，程序将继续运行（监听不可用）")
                self._listener = None
                self._running = False

    def stop(self) -> None:
        """停止监听并确保线程退出（FR-24：无残留线程）。"""

        with self._lock:
            listener = self._listener
            if listener is not None:
                try:
                    listener.stop()
                    join = getattr(listener, "join", None)
                    if callable(join):
                        join(timeout=2.0)
                except Exception:  # noqa: BLE001
                    logger.exception("停止全局键盘监听时发生异常")
                finally:
                    self._listener = None
            self._running = False
        logger.info("全局键盘监听已停止")

    def is_running(self) -> bool:
        """返回监听是否处于运行状态。"""

        return self._running and self._listener is not None

    # ------------------------------------------------------------------ #
    # 回调（工作线程！禁止触碰 Qt widget）
    # ------------------------------------------------------------------ #
    def _on_press(self, key: Any) -> None:
        """按键回调：仅向信号桥投递时间戳。

        Args:
            key: pynput 传入的按键对象（此处不使用）。
        """

        try:
            self._bridge.emit_keystroke(time.monotonic())
        except Exception:  # noqa: BLE001 —— 回调异常绝不冒泡到监听线程
            logger.exception("键盘回调处理异常（已忽略）")


__all__ = ["KeystrokeBridge", "KeyboardListener"]
