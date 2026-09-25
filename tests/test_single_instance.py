"""app.single_instance 单实例守卫单元测试。

用**唯一管道名**（``uuid4``）构造，绝不触碰程序真实的
``C.SINGLE_INSTANCE_KEY`` —— 否则会与正在运行的宠物实例互相干扰。

依赖 ``qapp``（pytest-qt）：``QLocalServer`` 的 ``newConnection`` 需要事件
循环派发，故断言激活信号前先 ``processEvents()``。
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from PySide6.QtNetwork import QLocalServer

from desktop_pet.app.single_instance import SingleInstanceGuard


def _unique_key() -> str:
    return f"desktop-pet-test-{uuid4().hex}"


@pytest.fixture()
def local_server_available(qapp) -> bool:  # noqa: ARG001
    """当前环境能否使用 QLocalServer（受限环境直接 skip，不误报失败）。"""

    key = _unique_key()
    probe = QLocalServer()
    if not probe.listen(key):
        pytest.skip(f"QLocalServer 在当前环境不可用：{probe.errorString()}")
    probe.close()
    QLocalServer.removeServer(key)
    return True


# --------------------------------------------------------------------------- #
# 首个实例
# --------------------------------------------------------------------------- #
def test_first_instance_acquires_and_releases(local_server_available: bool) -> None:
    """首个实例 acquire 成功；release 幂等且可重复调用。"""

    guard = SingleInstanceGuard(_unique_key())
    assert guard.acquire() is True
    guard.release()
    guard.release()  # 幂等：二次释放不抛异常


def test_release_allows_new_instance_to_acquire(local_server_available: bool) -> None:
    """前一个实例释放后，新实例应能取到守卫（避免退出后无法再启动）。"""

    key = _unique_key()
    first = SingleInstanceGuard(key)
    assert first.acquire() is True
    first.release()

    second = SingleInstanceGuard(key)
    try:
        assert second.acquire() is True
    finally:
        second.release()


# --------------------------------------------------------------------------- #
# 第二个实例
# --------------------------------------------------------------------------- #
def test_second_instance_is_rejected(local_server_available: bool, qapp) -> None:
    """已有实例在跑时，第二个 acquire 返回 False（调用方据此退出进程）。"""

    key = _unique_key()
    first = SingleInstanceGuard(key)
    assert first.acquire() is True
    second = SingleInstanceGuard(key)
    try:
        assert second.acquire() is False
    finally:
        second.release()
        first.release()


def test_second_instance_signals_first_to_reveal(local_server_available: bool, qapp) -> None:
    """第二个实例的启动请求应让原实例收到 activated（宠物显形）。"""

    key = _unique_key()
    first = SingleInstanceGuard(key)
    assert first.acquire() is True

    fired: list[int] = []
    first.activated.connect(lambda: fired.append(1))

    second = SingleInstanceGuard(key)
    try:
        assert second.acquire() is False
        qapp.processEvents()  # 派发 newConnection → activated
        assert fired == [1]
    finally:
        second.release()
        first.release()


def test_stale_pipe_is_reclaimed(local_server_available: bool) -> None:
    """前次进程异常退出留下的陈旧管道（removeServer 可清）不应挡住新实例。

    模拟方式：直接以同名 key 起一个裸 ``QLocalServer`` 再 ``close()`` 而不
    ``removeServer`` —— 这正是崩溃残留的状态；新守卫应能清理并成功监听。
    """

    key = _unique_key()
    stale = QLocalServer()
    assert stale.listen(key)
    stale.close()  # 不 removeServer → 管道残留

    guard = SingleInstanceGuard(key)
    try:
        assert guard.acquire() is True
    finally:
        guard.release()
