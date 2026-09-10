"""ui.tray —— 系统托盘（图标 + 右键菜单 + 信号）。

仅负责展示与发信号，**不含业务判定逻辑**（架构 §1.2）。
菜单项：恢复显示 / 暂停监听 / 缩放三档 / 最小化到托盘 / 开机自启 / 退出。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig

logger = logging.getLogger(__name__)

#: 缩放档位显示文案
_SCALE_LABELS = {
    0.8: "80%",
    1.0: "100%",
    1.2: "120%",
}


class TrayController(QObject):
    """系统托盘控制器。"""

    listen_toggled = Signal(bool)
    scale_selected = Signal(float)
    minimize_requested = Signal()
    restore_requested = Signal()
    autostart_toggled = Signal(bool)
    quit_requested = Signal()
    bubble_toggled = Signal(bool)

    def __init__(self, icon: QIcon, cfg: AppConfig) -> None:
        """构造托盘控制器。

        Args:
            icon: 猫脸托盘图标（由 :meth:`PetRenderer.build_tray_icon` 生成）。
            cfg: 当前配置（用于初始化勾选状态）。
        """

        super().__init__()
        self._icon = icon
        self._cfg = cfg

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(C.TRAY_TOOLTIP)

        self._menu = QMenu()
        self._action_restore: QAction | None = None
        self._action_listen: QAction | None = None
        self._action_bubble: QAction | None = None
        self._action_minimize: QAction | None = None
        self._action_autostart: QAction | None = None
        self._action_quit: QAction | None = None
        self._scale_group: QActionGroup | None = None
        self._scale_actions: dict[float, QAction] = {}

        self._build_menu()

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    @property
    def menu(self) -> QMenu:
        """暴露菜单实例，供宠物窗口右键复用（FR-19）。"""

        return self._menu

    def show(self) -> None:
        """显示托盘图标。"""

        self._tray.show()

    def notify(self, title: str, msg: str) -> None:
        """弹出系统通知（失败不抛异常）。"""

        try:
            self._tray.showMessage(title, msg, self._icon, 4000)
        except Exception:  # noqa: BLE001 —— 托盘通知失败不应影响主流程
            logger.exception("托盘通知失败：%s / %s", title, msg)

    def set_listen_checked(self, checked: bool) -> None:
        """同步"监听开关"勾选状态（不触发信号）。"""

        if self._action_listen is not None:
            self._action_listen.blockSignals(True)
            self._action_listen.setChecked(bool(checked))
            self._action_listen.blockSignals(False)

    def set_scale_checked(self, scale: float) -> None:
        """同步缩放档勾选状态（不触发信号）。"""

        for value, action in self._scale_actions.items():
            action.blockSignals(True)
            action.setChecked(abs(value - float(scale)) < 1e-6)
            action.blockSignals(False)

    def set_autostart_checked(self, checked: bool) -> None:
        """同步开机自启勾选状态（不触发信号）。"""

        if self._action_autostart is not None:
            self._action_autostart.blockSignals(True)
            self._action_autostart.setChecked(bool(checked))
            self._action_autostart.blockSignals(False)

    def set_bubble_checked(self, checked: bool) -> None:
        """同步气泡提示勾选状态（不触发信号）。"""

        if self._action_bubble is not None:
            self._action_bubble.blockSignals(True)
            self._action_bubble.setChecked(bool(checked))
            self._action_bubble.blockSignals(False)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _build_menu(self) -> None:
        """构建右键菜单。"""

        self._action_restore = QAction("显示宠物", self._menu)
        self._action_restore.triggered.connect(self.restore_requested.emit)

        self._action_listen = QAction("监听键盘", self._menu)
        self._action_listen.setCheckable(True)
        self._action_listen.setChecked(bool(self._cfg.listen_enabled))
        self._action_listen.toggled.connect(self.listen_toggled.emit)

        self._action_bubble = QAction("气泡提示", self._menu)
        self._action_bubble.setCheckable(True)
        self._action_bubble.setChecked(bool(self._cfg.bubble_enabled))
        self._action_bubble.toggled.connect(self.bubble_toggled.emit)

        scale_menu = QMenu("大小", self._menu)
        self._scale_group = QActionGroup(self._menu)
        self._scale_group.setExclusive(True)
        for value in C.SCALES:
            action = QAction(_SCALE_LABELS.get(value, f"{int(value * 100)}%"), scale_menu)
            action.setCheckable(True)
            action.setChecked(abs(value - float(self._cfg.scale)) < 1e-6)
            action.triggered.connect(lambda _checked=False, v=value: self.scale_selected.emit(v))
            self._scale_group.addAction(action)
            scale_menu.addAction(action)
            self._scale_actions[value] = action

        self._action_minimize = QAction("最小化到托盘", self._menu)
        self._action_minimize.triggered.connect(self.minimize_requested.emit)

        self._action_autostart = QAction("开机自启", self._menu)
        self._action_autostart.setCheckable(True)
        self._action_autostart.setChecked(bool(self._cfg.autostart))
        self._action_autostart.toggled.connect(self.autostart_toggled.emit)

        self._action_quit = QAction("退出", self._menu)
        self._action_quit.triggered.connect(self.quit_requested.emit)

        self._menu.addAction(self._action_restore)
        self._menu.addAction(self._action_listen)
        self._menu.addAction(self._action_bubble)
        self._menu.addMenu(scale_menu)
        self._menu.addAction(self._action_minimize)
        self._menu.addSeparator()
        self._menu.addAction(self._action_autostart)
        self._menu.addSeparator()
        self._menu.addAction(self._action_quit)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """托盘图标点击：双击恢复窗口，单击弹出菜单。"""

        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_requested.emit()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._menu.popup(self._menu.cursor().pos())


__all__ = ["TrayController"]
