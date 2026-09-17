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
    # —— 日语学习（ui 层只发信号，业务判定在 app/controller）——
    jp_enabled_toggled = Signal(bool)
    jp_level_selected = Signal(str)
    jp_duration_selected = Signal(int)
    jp_daily_limit_selected = Signal(int)
    jp_show_now_requested = Signal()
    jp_vocab_requested = Signal()
    jp_log_requested = Signal()

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
        # 日语学习菜单组
        self._action_jp: QAction | None = None
        self._jp_level_menu: QMenu | None = None
        self._jp_level_group: QActionGroup | None = None
        self._jp_level_actions: dict[str, QAction] = {}
        self._jp_duration_menu: QMenu | None = None
        self._jp_duration_group: QActionGroup | None = None
        self._jp_duration_actions: dict[int, QAction] = {}
        self._jp_daily_limit_menu: QMenu | None = None
        self._jp_daily_limit_group: QActionGroup | None = None
        self._jp_daily_limit_actions: dict[int, QAction] = {}
        self._action_jp_show_now: QAction | None = None
        self._action_jp_vocab: QAction | None = None
        self._action_jp_log: QAction | None = None

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

    def set_jp_checked(self, checked: bool) -> None:
        """同步「日语学习」开关勾选状态（不触发信号）。"""

        if self._action_jp is not None:
            self._action_jp.blockSignals(True)
            self._action_jp.setChecked(bool(checked))
            self._action_jp.blockSignals(False)

    def set_jp_level_checked(self, level: str) -> None:
        """同步「难度」单选状态（不触发信号）。"""

        for value, action in self._jp_level_actions.items():
            action.blockSignals(True)
            action.setChecked(value == level)
            action.blockSignals(False)

    def set_jp_enabled(self, enabled: bool) -> None:
        """统一刷新日语菜单组：关闭时「难度/显示时长/每日数量/立即显示」置灰；
        生词本/学习记录始终可用。"""

        enabled = bool(enabled)
        if self._jp_level_menu is not None:
            self._jp_level_menu.setEnabled(enabled)
        if self._jp_duration_menu is not None:
            self._jp_duration_menu.setEnabled(enabled)
        if self._jp_daily_limit_menu is not None:
            self._jp_daily_limit_menu.setEnabled(enabled)
        if self._action_jp_show_now is not None:
            self._action_jp_show_now.setEnabled(enabled)

    def set_jp_duration_checked(self, value: int) -> None:
        """同步「显示时长」单选状态（不触发信号）。"""

        for option, action in self._jp_duration_actions.items():
            action.blockSignals(True)
            action.setChecked(option == int(value))
            action.blockSignals(False)

    def set_jp_daily_limit_checked(self, value: int) -> None:
        """同步「每日数量」单选状态（不触发信号）。"""

        for option, action in self._jp_daily_limit_actions.items():
            action.blockSignals(True)
            action.setChecked(option == int(value))
            action.blockSignals(False)

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

        # —— 日语学习菜单组（开关 + 难度/显示时长/每日数量子菜单 + 立即显示 + 生词本/记录）——
        self._action_jp = QAction(C.JP_MENU_TITLE, self._menu)
        self._action_jp.setCheckable(True)
        self._action_jp.setChecked(bool(self._cfg.jp_enabled))
        self._action_jp.toggled.connect(self.jp_enabled_toggled.emit)

        self._jp_level_menu = QMenu(C.JP_MENU_LEVEL, self._menu)
        self._jp_level_group = QActionGroup(self._menu)
        self._jp_level_group.setExclusive(True)
        for level in C.JP_LEVELS:
            action = QAction(C.JP_LEVEL_LABELS.get(level, level), self._jp_level_menu)
            action.setCheckable(True)
            action.setChecked(level == self._cfg.jp_level)
            action.triggered.connect(
                lambda _checked=False, lv=level: self.jp_level_selected.emit(lv)
            )
            self._jp_level_group.addAction(action)
            self._jp_level_menu.addAction(action)
            self._jp_level_actions[level] = action

        self._jp_duration_menu = QMenu(C.JP_MENU_DURATION, self._menu)
        self._jp_duration_group = QActionGroup(self._menu)
        self._jp_duration_group.setExclusive(True)
        for option in C.JP_BUBBLE_DURATION_OPTIONS:
            label = C.JP_BUBBLE_DURATION_LABELS.get(option, f"{option} 秒")
            action = QAction(label, self._jp_duration_menu)
            action.setCheckable(True)
            action.setChecked(option == self._cfg.jp_bubble_duration_s)
            action.triggered.connect(
                lambda _checked=False, opt=option: self.jp_duration_selected.emit(opt)
            )
            self._jp_duration_group.addAction(action)
            self._jp_duration_menu.addAction(action)
            self._jp_duration_actions[option] = action

        self._jp_daily_limit_menu = QMenu(C.JP_MENU_DAILY_LIMIT, self._menu)
        self._jp_daily_limit_group = QActionGroup(self._menu)
        self._jp_daily_limit_group.setExclusive(True)
        for option in C.JP_DAILY_LIMIT_OPTIONS:
            label = C.JP_DAILY_LIMIT_LABELS.get(option, f"{option} 个")
            action = QAction(label, self._jp_daily_limit_menu)
            action.setCheckable(True)
            action.setChecked(option == self._cfg.jp_daily_limit)
            action.triggered.connect(
                lambda _checked=False, opt=option: self.jp_daily_limit_selected.emit(opt)
            )
            self._jp_daily_limit_group.addAction(action)
            self._jp_daily_limit_menu.addAction(action)
            self._jp_daily_limit_actions[option] = action

        self._action_jp_show_now = QAction(C.JP_MENU_SHOW_NOW, self._menu)
        self._action_jp_show_now.triggered.connect(
            lambda _checked=False: self.jp_show_now_requested.emit()
        )

        self._action_jp_vocab = QAction(C.JP_MENU_VOCAB, self._menu)
        self._action_jp_vocab.triggered.connect(
            lambda _checked=False: self.jp_vocab_requested.emit()
        )

        self._action_jp_log = QAction(C.JP_MENU_LOG, self._menu)
        self._action_jp_log.triggered.connect(
            lambda _checked=False: self.jp_log_requested.emit()
        )

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
        self._menu.addSeparator()
        self._menu.addAction(self._action_jp)
        self._menu.addMenu(self._jp_level_menu)
        self._menu.addMenu(self._jp_duration_menu)
        self._menu.addMenu(self._jp_daily_limit_menu)
        self._menu.addAction(self._action_jp_show_now)
        self._menu.addAction(self._action_jp_vocab)
        self._menu.addAction(self._action_jp_log)
        self._menu.addSeparator()
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
