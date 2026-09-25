"""desktop_pet.main —— 程序入口。

创建 ``QApplication``，配置日志与高分屏策略，装配并启动 :class:`PetAppController`。
"""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler

from desktop_pet import __version__
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore

logger = logging.getLogger(__name__)

#: 日志轮转参数
_LOG_MAX_BYTES: int = 512 * 1024
_LOG_BACKUP_COUNT: int = 2


def _configure_logging() -> None:
    """配置根日志：INFO 级别，输出到 ``%APPDATA%\\desktop-pet\\app.log`` 并轮转。

    任何日志配置失败都不得阻止程序启动。
    """

    root = logging.getLogger()
    if root.handlers:
        # 已配置（例如被测试或重复调用）则直接返回
        return
    root.setLevel(logging.INFO)
    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    # 文件（轮转）
    try:
        log_path = ConfigStore.log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            str(log_path),
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except Exception:  # noqa: BLE001 —— 日志文件不可写时降级为仅控制台
        root.exception("配置文件日志失败，仅使用控制台输出")


def _configure_high_dpi() -> None:
    """设置高分屏缩放取整策略（Qt 6 默认启用 High-DPI 缩放）。

    需在 ``QApplication`` 创建前调用。
    """

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication

        policy = Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        QGuiApplication.setHighDpiScaleFactorRoundingPolicy(policy)
    except Exception:  # noqa: BLE001 —— 个别平台不支持则忽略
        logging.getLogger(__name__).debug("设置高分屏策略失败，使用默认", exc_info=True)


def main() -> int:
    """程序主入口。

    Returns:
        进程退出码（``QApplication.exec()`` 的返回值）。
    """

    _configure_logging()
    logger.info("desktop-pet v%s 启动", __version__)

    _configure_high_dpi()

    try:
        from PySide6.QtWidgets import QApplication
    except Exception:  # noqa: BLE001 —— 缺少依赖时给出清晰提示而非堆栈崩溃
        logger.exception("无法导入 PySide6，请先执行 `pip install -r requirements.txt`")
        return 1

    app = QApplication(sys.argv)
    app.setApplicationName(C.APP_DISPLAY_NAME)
    app.setApplicationDisplayName(C.APP_DISPLAY_NAME)
    app.setOrganizationName("desktop-pet")
    # 使用托盘 + Tool 窗口，关闭"最后窗口关闭即退出"以免最小化到托盘时退出
    app.setQuitOnLastWindowClosed(False)

    # 单实例守卫（必须在 QApplication 之后：QLocalServer 依赖 Qt 事件机制）：
    # 已有实例在跑时，通知它显形（从托盘恢复并前置），本进程安静退出。
    from desktop_pet.app.single_instance import SingleInstanceGuard

    guard = SingleInstanceGuard(C.SINGLE_INSTANCE_KEY)
    if not guard.acquire():
        return 0

    try:
        # 延迟导入，确保 QApplication 已存在（Qt 托盘/绘制对象需要）
        from desktop_pet.app.controller import PetAppController

        store = ConfigStore(ConfigStore.default_path())
        controller = PetAppController(app, store)
        # 二次启动 → 已有实例的宠物显形并前置
        guard.activated.connect(controller.reveal)
        controller.start()
    except Exception:  # noqa: BLE001 —— 启动失败给出日志并返回非零码
        logger.exception("桌面宠物启动失败")
        guard.release()
        return 1

    try:
        return app.exec()
    finally:
        guard.release()


if __name__ == "__main__":
    sys.exit(main())
