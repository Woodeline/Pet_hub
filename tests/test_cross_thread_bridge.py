"""跨线程信号桥测试（FR-01/FR-02，架构唯一跨线程点 §9.7）。

验证 Qt 的 ``AutoConnection`` 在跨线程 emit 时真的排队投递到主线程，
以及监听器启停无残留线程、回调异常不崩溃。

**注意**：不合成真实按键（避免把字符打进用户活动窗口）；真机端到端验证见
``tests/manual_checklist.md``。
"""

from __future__ import annotations

import sys
import threading
import time

import pytest
from PySide6.QtCore import QEventLoop, QObject, QTimer, Slot

from desktop_pet.app.keyboard_listener import KeystrokeBridge, KeyboardListener


class _Receiver(QObject):
    """记录收到的值以及处理它们的线程 id。"""

    def __init__(self) -> None:
        super().__init__()
        self.values: list[float] = []
        self.thread_ids: list[int] = []

    @Slot(float)
    def on_keystroke(self, timestamp: float) -> None:
        self.values.append(timestamp)
        self.thread_ids.append(threading.get_ident())


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# --------------------------------------------------------------------------- #
# 1. 跨线程 QueuedConnection 投递
# --------------------------------------------------------------------------- #
def test_signal_delivered_across_threads_to_main(qtbot) -> None:
    bridge = KeystrokeBridge()
    receiver = _Receiver()
    bridge.keystroke.connect(receiver.on_keystroke)
    main_thread_id = threading.get_ident()

    def worker() -> None:
        bridge.emit_keystroke(123.5)

    thread = threading.Thread(target=worker, name="emit-worker")
    thread.start()
    thread.join(timeout=2.0)

    _wait(300)  # 事件循环处理排队信号

    assert receiver.values == [123.5], "跨线程信号未送达"
    assert receiver.thread_ids == [main_thread_id], (
        "槽未在主线程执行 —— QueuedConnection 未生效（可能被当成 DirectConnection）"
    )


def test_multiple_emits_preserve_order(qtbot) -> None:
    bridge = KeystrokeBridge()
    receiver = _Receiver()
    bridge.keystroke.connect(receiver.on_keystroke)

    payload = [1.0, 2.0, 3.0, 4.0, 5.0]

    def worker() -> None:
        for value in payload:
            bridge.emit_keystroke(value)

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join(timeout=2.0)
    _wait(300)

    assert receiver.values == payload


def test_concurrent_workers_deliver_all(qtbot) -> None:
    bridge = KeystrokeBridge()
    receiver = _Receiver()
    bridge.keystroke.connect(receiver.on_keystroke)

    def worker(base: float) -> None:
        for i in range(20):
            bridge.emit_keystroke(base + i)

    threads = [threading.Thread(target=worker, args=(b,)) for b in (0.0, 100.0, 200.0)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
    _wait(400)

    assert len(receiver.values) == 60
    assert all(tid == threading.get_ident() for tid in receiver.thread_ids)


# --------------------------------------------------------------------------- #
# 2. 监听器生命周期：无残留线程（FR-24）
# --------------------------------------------------------------------------- #
def test_listener_start_stop_no_residual_threads(qtbot) -> None:
    bridge = KeystrokeBridge()
    listener = KeyboardListener(bridge)

    before = {t.ident for t in threading.enumerate()}
    listener.start()
    started = listener.is_running()
    new_after_start = [t for t in threading.enumerate() if t.ident not in before]

    # 若环境允许启动，则应出现一个监听线程
    assert (not started) or len(new_after_start) >= 1, "监听器声称已启动但未创建线程"

    listener.stop()

    deadline = time.time() + 3.0
    leaked: list[threading.Thread] = []
    while time.time() < deadline:
        leaked = [t for t in threading.enumerate() if t.ident not in before and t.is_alive()]
        if not leaked:
            break
        time.sleep(0.05)

    assert not leaked, f"stop() 后存在残留线程：{leaked}"
    assert listener.is_running() is False


def test_listener_start_is_idempotent_and_stop_safe(qtbot) -> None:
    bridge = KeystrokeBridge()
    listener = KeyboardListener(bridge)
    listener.start()
    listener.start()  # 重复启动应为 no-op
    listener.stop()
    listener.stop()  # 重复停止不应抛异常
    assert listener.is_running() is False


# --------------------------------------------------------------------------- #
# 3. 回调异常不崩溃（FR-01）
# --------------------------------------------------------------------------- #
def test_callback_exception_does_not_propagate(qtbot) -> None:
    class _BoomBridge(KeystrokeBridge):
        def emit_keystroke(self, timestamp: float) -> None:
            raise RuntimeError("模拟信号桥故障")

    listener = KeyboardListener(_BoomBridge())
    # 直接调用回调，必须被捕获而不是冒泡（否则会杀死监听线程）
    try:
        listener._on_press("a")
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"_on_press 未吞掉异常，监听线程会被杀死：{exc!r}")


def test_bridge_emits_float_signal(qtbot) -> None:
    bridge = KeystrokeBridge()
    seen: list[float] = []
    bridge.keystroke.connect(lambda v: seen.append(v))
    bridge.emit_keystroke(42)  # 传 int，应被转换为 float
    _wait(100)
    assert seen == [42.0]


# --------------------------------------------------------------------------- #
# 4. macOS TSM 主线程约束（2026-11-12 实机 SIGTRAP 崩溃回归）
# --------------------------------------------------------------------------- #
@pytest.mark.skipif(sys.platform != "darwin", reason="TSM 主队列断言仅 macOS")
def test_tsm_input_source_calls_stay_on_main_thread(qtbot) -> None:
    """pynput 的 TSM 输入源调用必须全部发生在主线程（预取），监听线程零 TSM。

    macOS 26 对 TSM API 断言主队列；pynput 默认在监听线程进入/退出
    keycode_context 时调用 → dispatch_assert_queue_fail → SIGTRAP 整进程崩溃。
    """

    from pynput._util import darwin as darwin_util
    from pynput.keyboard import _darwin as darwin_backend

    main_tid = threading.get_ident()
    calls: list[int] = []
    original_fn = darwin_util.CarbonExtra.TISCopyCurrentKeyboardInputSource
    original_ctx = darwin_backend.keycode_context

    def spy():
        calls.append(threading.get_ident())
        return original_fn()

    darwin_util.CarbonExtra.TISCopyCurrentKeyboardInputSource = spy
    try:
        listener = KeyboardListener(KeystrokeBridge())
        listener.start()
        _wait(300)
        listener.stop()
    finally:
        darwin_util.CarbonExtra.TISCopyCurrentKeyboardInputSource = original_fn

    assert calls, "主线程未预取键盘布局上下文"
    assert all(tid == main_tid for tid in calls), f"TSM 在后台线程被调用：{calls}"
    assert darwin_backend.keycode_context is original_ctx, "stop 后未还原 pynput 原实现"
