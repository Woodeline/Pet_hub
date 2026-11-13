"""app.keyboard_listener —— pynput 守护线程 + Qt 跨线程信号桥（FR-01 / FR-24）。

线程模型（架构 §9.7）：
- ``pynput.keyboard.Listener`` 运行在**独立守护线程**。
- 回调 ``_on_press`` **只做一件事**：``bridge.emit_keystroke(ts)``，
  **绝不触碰任何 Qt widget**。跨线程由 Qt ``AutoConnection`` 自动排队投递到主线程。
- 任何异常都被捕获并记日志，**绝不让程序崩溃**。
- ``stop()`` 确保监听线程真正退出，无残留线程（FR-24）。
- macOS 26 的 TSM 输入源 API 断言主队列：键码上下文在主线程预取并缓存，
  监听线程不触碰 TSM（否则启停时 SIGTRAP 整进程崩溃）。
"""

from __future__ import annotations

import contextlib
import logging
import sys
import threading
import time
from typing import Any, Optional

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)


def macos_accessibility_trusted() -> bool:
    """返回 macOS「辅助功能」权限是否已授予（非 macOS 恒为 ``True``）。

    pynput 的 darwin 后端在进程不受信任时**只 warning 不抛错**——监听看似
    启动成功，却一个按键也收不到。这里显式调用 pyobjc 的
    ``AXIsProcessTrusted`` 探测真实状态，供上层给用户明确引导。
    """

    if sys.platform != "darwin":
        return True
    try:
        try:
            # pyobjc 中 AXIsProcessTrusted 属 ApplicationServices 框架
            from ApplicationServices import AXIsProcessTrusted  # type: ignore[import-untyped]
        except ImportError:  # 个别 pyobjc 版本从 Quartz 再导出
            from Quartz import AXIsProcessTrusted  # type: ignore[import-untyped]

        return bool(AXIsProcessTrusted())
    except Exception:  # noqa: BLE001 —— 探测失败不阻塞启动，按"已授权"放行
        logger.debug("macOS 辅助功能权限探测失败，按已授权放行", exc_info=True)
        return True


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
        self._keycode_cm: Optional[Any] = None
        self._keycode_original: Optional[Any] = None

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

                self._engage_main_thread_keycode_context()
                listener = keyboard.Listener(on_press=self._on_press)
                listener.daemon = True
                listener.start()
                self._listener = listener
                self._running = True
                logger.info("全局键盘监听已启动")
            except Exception:  # noqa: BLE001 —— FR-01：监听失败不崩溃
                logger.exception("启动全局键盘监听失败，程序将继续运行（监听不可用）")
                self._disengage_main_thread_keycode_context()
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
            self._disengage_main_thread_keycode_context()
        logger.info("全局键盘监听已停止")

    def is_running(self) -> bool:
        """返回监听是否处于运行状态。"""

        return self._running and self._listener is not None

    # ------------------------------------------------------------------ #
    # macOS TSM 主线程约束兜底
    # ------------------------------------------------------------------ #
    def _engage_main_thread_keycode_context(self) -> None:
        """在主线程预取 pynput 键码上下文，监听线程改用缓存替身。

        macOS 26 起 TSM 输入源 API（TISCopyCurrentKeyboardInputSource /
        CFRelease 触发的 isValidateInputSourceRef）断言主队列；pynput 的
        ``keycode_context`` 在监听线程进入/退出时调用它们 → SIGTRAP 整进程
        崩溃（2026-11-12 实机崩溃报告）。本方法在 start()（主线程）里完成
        全部 TSM 调用，监听线程只拿缓存的 ``(keyboard_type, layout_data)``。
        """

        if sys.platform != "darwin" or self._keycode_cm is not None:
            return
        try:
            from pynput.keyboard import _darwin as darwin_backend

            original = darwin_backend.keycode_context
            cm = original()
            context = cm.__enter__()
        except Exception:  # noqa: BLE001 —— 预取失败回退 pynput 默认行为
            logger.exception("预取键盘布局上下文失败，回退 pynput 默认行为")
            return
        self._keycode_original = original
        self._keycode_cm = cm

        @contextlib.contextmanager
        def _cached_context():
            yield context

        darwin_backend.keycode_context = _cached_context

    def _disengage_main_thread_keycode_context(self) -> None:
        """还原 pynput 原实现并在主线程释放上下文（CFRelease 同样须主队列）。"""

        cm = self._keycode_cm
        if cm is None:
            return
        self._keycode_cm = None
        original, self._keycode_original = self._keycode_original, None
        try:
            if original is not None:
                from pynput.keyboard import _darwin as darwin_backend

                darwin_backend.keycode_context = original
        except Exception:  # noqa: BLE001
            logger.exception("还原 pynput keycode_context 失败（已忽略）")
        try:
            cm.__exit__(None, None, None)
        except Exception:  # noqa: BLE001
            logger.exception("释放键盘布局上下文异常（已忽略）")

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


__all__ = ["KeystrokeBridge", "KeyboardListener", "macos_accessibility_trusted"]
