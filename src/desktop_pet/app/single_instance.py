"""app.single_instance —— 单实例守卫（QLocalServer / QLocalSocket 命名管道）。

用途：保证同一时刻只有一个宠物实例在跑。双击两次 exe 时，第二个进程应
**通知第一个实例显形**（从托盘/最小化恢复并前置）后安静退出，而不是起两只猫
争夺同一份 ``config.json``（后退出者覆盖前者的窗口位置与设置）。

线程/进程模型：全部在**主进程主线程**完成；仅在 ``QApplication`` 创建之后调用
（``QLocalServer`` 属于 QtNetwork，依赖事件循环）。本模块位于 ``app`` 层，
故可使用 Qt。

健壮性约定（单实例是体验优化，不是关键功能，**绝不阻断启动**）：

- 监听失败（管道名被占 / 权限不足）→ 记警告并放行，程序照常启动；
- 前次进程崩溃留下的陈旧管道 → ``removeServer`` 后重试监听；
- 任何异常都被捕获，最坏情况退化为「没有守卫」（等同修复前行为）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

#: 探测已有实例的连接/写入等待（毫秒）。取值小：本地命名管道是即时的，
#: 超过该值说明没有实例在监听，不必拖慢启动。
_PROBE_TIMEOUT_MS: int = 300

#: 第二个实例发给首个实例的负载（当前无指令语义，仅作「我来过」信号）
_ACTIVATE_PAYLOAD: bytes = b"activate"


class SingleInstanceGuard(QObject):
    """基于命名管道的单实例守卫。

    用法::

        guard = SingleInstanceGuard(C.SINGLE_INSTANCE_KEY)
        if not guard.acquire():
            return 0                      # 已有实例：本进程退出
        guard.activated.connect(controller.reveal)   # 二次启动 → 宠物显形
        ...
        guard.release()                   # 退出前释放管道
    """

    #: 第二个实例请求启动 → 原实例应显形（从托盘恢复并前置）
    activated = Signal()

    def __init__(self, key: str, parent: QObject | None = None) -> None:
        """构造守卫。

        Args:
            key: 命名管道名（全局唯一，见 :data:`constants.SINGLE_INSTANCE_KEY`）。
            parent: Qt 父对象（可选）。
        """

        super().__init__(parent)
        self._key: str = str(key)
        self._server: QLocalServer | None = None

    # ------------------------------------------------------------------ #
    # 生命周期
    # ------------------------------------------------------------------ #
    def acquire(self) -> bool:
        """尝试成为唯一实例。

        Returns:
            ``True`` = 本进程是首个实例（已开始监听）；
            ``False`` = 已有实例在运行（已通知其显形），调用方**应立即退出本进程**。
        """

        try:
            if self._notify_existing_instance():
                logger.info("检测到已有实例在运行，本次启动退出")
                return False
            return self._listen()
        except Exception:  # noqa: BLE001 —— 守卫异常绝不阻断启动
            logger.exception("单实例检查异常（已忽略，本次启动不设守卫）")
            return True

    def release(self) -> None:
        """释放监听与命名管道（退出流程调用；可重复调用）。"""

        server = self._server
        self._server = None
        if server is None:
            return
        try:
            server.close()
            # 主动移除管道：否则崩溃/强杀后残留的名字会让下次 removeServer 才有救
            QLocalServer.removeServer(self._key)
        except Exception:  # noqa: BLE001
            logger.exception("释放单实例守卫失败（已忽略）")

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _notify_existing_instance(self) -> bool:
        """探测是否已有实例在监听；有则请求它显形并返回 ``True``。"""

        socket = QLocalSocket()
        socket.connectToServer(self._key)
        if not socket.waitForConnected(_PROBE_TIMEOUT_MS):
            # 没有实例在监听（或监听方繁忙）：本进程继续走 listen 分支。
            socket.abort()
            return False
        try:
            socket.write(_ACTIVATE_PAYLOAD)
            socket.flush()
            socket.waitForBytesWritten(_PROBE_TIMEOUT_MS)
        except Exception:  # noqa: BLE001 —— 通知失败不影响「已有实例」的判定
            logger.debug("通知已有实例显形失败（已忽略）", exc_info=True)
        finally:
            socket.disconnectFromServer()
        return True

    def _listen(self) -> bool:
        """清理陈旧管道后开始监听。

        Returns:
            ``True`` = 已成为唯一实例（或监听失败但选择放行）；
            实际上本方法的 ``False`` 分支不存在——监听失败时**放行**而非拒绝启动，
            故返回 True 并记警告（避免守卫故障导致程序无法启动）。
        """

        # 前次进程被强杀时管道名可能残留 → 先清再监听，否则 listen 必失败。
        QLocalServer.removeServer(self._key)
        server = QLocalServer(self)
        server.newConnection.connect(self._on_new_connection)
        if not server.listen(self._key):
            logger.warning(
                "单实例监听失败（%s），本次启动不设守卫（仍可正常使用）",
                server.errorString(),
            )
            server.deleteLater()
            return True
        self._server = server
        logger.info("单实例守卫已就绪")
        return True

    def _on_new_connection(self) -> None:
        """第二个实例连上来 → 丢弃负载、断开连接并请求显形。"""

        server = self._server
        if server is None:
            return
        socket = server.nextPendingConnection()
        if socket is None:
            return
        try:
            socket.readAll()
            socket.disconnectFromServer()
        except Exception:  # noqa: BLE001 —— 收尾失败不影响显形
            logger.debug("处理第二实例连接异常（已忽略）", exc_info=True)
        socket.deleteLater()
        logger.info("收到二次启动请求，宠物显形")
        self.activated.emit()


__all__ = ["SingleInstanceGuard"]
