"""ui.tray —— 系统托盘（图标 + 右键菜单 + 信号）。

仅负责展示与发信号，**不含业务判定逻辑**（架构 §1.2）。
菜单按大类分组（阶段 E 信息架构重组）：窗口控制（显示宠物 / 最小化到托盘）→
开关（监听键盘 / 气泡提示）→ **日语学习**子菜单（开关 + 立即显示 + 节奏三档 +
生词本 / 学习记录）→ 外观（大小 / 主题）→ 偏好（开机自启 / 减少动效）→ 退出。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction, QActionGroup, QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidgetAction

from desktop_pet import __version__
from desktop_pet.core import constants as C
from desktop_pet.core import theme as core_theme
from desktop_pet.core.config import AppConfig
from desktop_pet.ui.icon_factory import menu_icon
from desktop_pet.ui.menu_rows import (
    MenuGroupLabelWidget,
    MenuHeaderWidget,
    make_row_action,
)
from desktop_pet.ui.menu_shadow import ShadowMenu

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
    reduce_motion_toggled = Signal(bool)
    theme_selected = Signal(str)
    #: 皮肤包（MOD）切换：取值 ``vector`` / ``""``(自动) / 包名
    skin_selected = Signal(str)
    quit_requested = Signal()
    bubble_toggled = Signal(bool)
    #: 打开「气泡文案」设置对话框
    bubble_text_requested = Signal()
    # —— 日语学习（ui 层只发信号，业务判定在 app/controller）——
    jp_enabled_toggled = Signal(bool)
    jp_level_selected = Signal(str)
    jp_duration_selected = Signal(int)
    jp_daily_limit_selected = Signal(int)
    jp_review_limit_selected = Signal(int)
    jp_show_now_requested = Signal()
    jp_vocab_requested = Signal()
    jp_mastered_requested = Signal()
    jp_log_requested = Signal()
    jp_stats_requested = Signal()
    jp_import_bank_requested = Signal()
    #: 打开「数据管理」窗口（导出 Anki/CSV、一键备份与还原）
    data_manager_requested = Signal()
    #: 手动检查更新（GitHub Releases）
    update_check_requested = Signal()
    #: 自动检查更新开关
    update_auto_toggled = Signal(bool)

    def __init__(self, icon: QIcon, cfg: AppConfig) -> None:
        """构造托盘控制器。

        Args:
            icon: 猫脸托盘图标（由 :meth:`PetRenderer.build_tray_icon` 生成）。
            cfg: 当前配置（用于初始化勾选状态）。
        """

        super().__init__()
        self._icon = icon
        self._cfg = cfg
        # 富条目实时数据 provider（由 controller 注入只读回调；缺省回 0/False）。
        self._data_providers: dict[str, Callable[[], int]] = {}
        self._update_available = False
        self._submenu_row_actions: dict[QMenu, QWidgetAction] = {}
        self._all_menus: list[QMenu] = []

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip(C.TRAY_TOOLTIP)

        self._menu = ShadowMenu()
        self._action_restore: QAction | None = None
        self._action_listen: QAction | None = None
        self._action_bubble: QAction | None = None
        self._action_bubble_text: QAction | None = None
        self._action_minimize: QAction | None = None
        self._action_autostart: QAction | None = None
        self._action_reduce_motion: QAction | None = None
        self._action_quit: QAction | None = None
        self._scale_group: QActionGroup | None = None
        self._scale_menu: QMenu | None = None
        self._scale_actions: dict[float, QAction] = {}
        # 主题皮肤菜单组（「自动」+ 6 套皮肤，单选）
        self._theme_menu: QMenu | None = None
        self._theme_group: QActionGroup | None = None
        self._theme_actions: dict[str, QAction] = {}
        # 皮肤包（MOD）菜单组（「矢量」+「自动」+ 各已装包，单选）
        self._skin_menu: QMenu | None = None
        self._skin_group: QActionGroup | None = None
        self._skin_actions: dict[str, QAction] = {}
        # —— 日语学习菜单组（菜单按大类重组：开关 + 子项收进同一个「日语学习」子菜单）——
        self._jp_menu: QMenu | None = None
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
        self._jp_review_limit_menu: QMenu | None = None
        self._jp_review_limit_group: QActionGroup | None = None
        self._jp_review_limit_actions: dict[int, QAction] = {}
        self._action_jp_show_now: QAction | None = None
        self._action_jp_vocab: QAction | None = None
        self._action_jp_mastered: QAction | None = None
        self._action_jp_log: QAction | None = None
        self._action_jp_stats: QAction | None = None
        self._action_jp_import: QAction | None = None

        self._build_menu()
        self._all_menus = [
            self._menu, self._jp_menu, self._jp_level_menu, self._jp_duration_menu,
            self._jp_daily_limit_menu, self._jp_review_limit_menu,
            self._scale_menu, self._theme_menu, self._skin_menu,
        ]
        self._sync_motion()
        self._menu.aboutToShow.connect(self._touch)

        self._tray.setContextMenu(self._menu)
        self._tray.activated.connect(self._on_activated)

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    @property
    def menu(self) -> QMenu:
        """暴露菜单实例，供宠物窗口右键复用（FR-19）。"""

        return self._menu

    # ------------------------------------------------------------------ #
    # 富条目实时数据 / 刷新 / 动效
    # ------------------------------------------------------------------ #
    def set_data_providers(
        self,
        *,
        vocab_count: Callable[[], int] | None = None,
        mastered_count: Callable[[], int] | None = None,
        today_words: Callable[[], int] | None = None,
    ) -> None:
        """注入只读数据回调（生词本 / 已掌握 / 今日词数），供徽标与头部进度实时读取。"""

        if vocab_count is not None:
            self._data_providers["vocab_count"] = vocab_count
        if mastered_count is not None:
            self._data_providers["mastered_count"] = mastered_count
        if today_words is not None:
            self._data_providers["today_words"] = today_words
        self._touch()

    def set_update_available(self, available: bool) -> None:
        """设置「检查更新」红点状态（controller 在比对版本后调用）。"""

        self._update_available = bool(available)
        self._touch()

    def _touch(self) -> None:
        """触发全部菜单重绘（富条目 provider 在 paint 时实时读状态）。"""

        for menu in self._all_menus:
            menu.update()

    def _sync_motion(self) -> None:
        """reduce_motion 开启时入场动效直通 0，否则取 MENU_MOTION_MS。"""

        ms = 0 if self._cfg.reduce_motion else C.MENU_MOTION_MS
        for menu in self._all_menus:
            if isinstance(menu, ShadowMenu):
                menu.motion_ms = ms

    def _resolved_theme(self) -> str:
        return core_theme.resolve_theme(datetime.now().month, self._cfg.theme)

    def _accent(self) -> str:
        return core_theme.ui_accent_for_theme(self._resolved_theme())

    def _stops(self) -> tuple:
        return core_theme.theme_stops(self._resolved_theme())

    def _today(self) -> int:
        return self._data_providers.get("today_words", lambda: 0)()

    def _scale_value(self) -> str:
        return f"{int(round(self._cfg.scale * 100))}%"

    def _theme_value(self) -> str:
        return C.THEME_NAMES.get(self._resolved_theme(), self._resolved_theme())

    def _jp_value(self) -> str:
        if not self._cfg.jp_enabled:
            return "已关闭"
        return f"{self._cfg.jp_level} · {self._cfg.jp_daily_limit} 词/日"

    def _jp_duration_value(self) -> str:
        return C.JP_BUBBLE_DURATION_LABELS.get(
            self._cfg.jp_bubble_duration_s, f"{self._cfg.jp_bubble_duration_s} 秒"
        )

    def _jp_daily_value(self) -> str:
        return C.JP_DAILY_LIMIT_LABELS.get(
            self._cfg.jp_daily_limit, f"{self._cfg.jp_daily_limit} 个"
        )

    def _jp_review_value(self) -> str:
        return C.JP_REVIEW_DAILY_LIMIT_LABELS.get(
            self._cfg.jp_review_daily_limit, f"{self._cfg.jp_review_daily_limit} 个"
        )

    def _vocab_badge(self) -> str:
        return str(self._data_providers.get("vocab_count", lambda: 0)())

    def _mastered_badge(self) -> str:
        return str(self._data_providers.get("mastered_count", lambda: 0)())

    def _update_badge(self) -> str | None:
        return "dot" if self._update_available else None

    def _status(self) -> tuple[bool, str]:
        on = bool(self._cfg.jp_enabled)
        if on:
            return True, f"专注中 · 今日 {self._today()}/{self._cfg.jp_daily_limit} 词"
        return False, "日语学习已关闭"

    def _progress(self) -> float:
        return self._today() / max(1, self._cfg.jp_daily_limit)

    def show(self) -> None:
        """显示托盘图标。"""

        self._tray.show()

    def notify(self, title: str, msg: str) -> None:
        """弹出系统通知（失败不抛异常）。"""

        try:
            self._tray.showMessage(title, msg, self._icon, 4000)
        except Exception:  # noqa: BLE001 —— 托盘通知失败不应影响主流程
            logger.exception("托盘通知失败：%s / %s", title, msg)

    def set_icon(self, icon: QIcon) -> None:
        """替换托盘图标（主题切换时跟随重建，P1）。"""

        self._icon = icon
        self._tray.setIcon(icon)

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

    def set_update_auto_checked(self, checked: bool) -> None:
        """同步「自动检查更新」勾选状态（不触发信号）。"""

        if self._action_update_auto is not None:
            self._action_update_auto.blockSignals(True)
            self._action_update_auto.setChecked(bool(checked))
            self._action_update_auto.blockSignals(False)

    def set_bubble_checked(self, checked: bool) -> None:
        """同步气泡提示勾选状态（不触发信号）。"""

        if self._action_bubble is not None:
            self._action_bubble.blockSignals(True)
            self._action_bubble.setChecked(bool(checked))
            self._action_bubble.blockSignals(False)

    def set_reduce_motion_checked(self, checked: bool) -> None:
        """同步「减少动效」勾选状态（不触发信号）。"""

        if self._action_reduce_motion is not None:
            self._action_reduce_motion.blockSignals(True)
            self._action_reduce_motion.setChecked(bool(checked))
            self._action_reduce_motion.blockSignals(False)
        self._sync_motion()
        self._touch()

    def set_theme_checked(self, value: str) -> None:
        """同步「主题」单选勾选状态（``blockSignals``，**不触发信号**）。

        Args:
            value: 用户选择的主题取值（``auto`` 或某套皮肤名）。
        """

        target = str(value)
        for key, action in self._theme_actions.items():
            action.blockSignals(True)
            action.setChecked(key == target)
            action.blockSignals(False)

    def set_skin_checked(self, value: str) -> None:
        """同步「皮肤」单选勾选状态（``blockSignals``，**不触发信号**）。

        指定包名可能不在菜单里（该包被删除/损坏，已回落自动）：此时勾选
        「自动」项，避免菜单无任何勾选的误导状态。
        """

        target = str(value)
        keys = set(self._skin_actions)
        if target not in keys:
            target = C.SKIN_NAME_AUTO
        for key, action in self._skin_actions.items():
            action.blockSignals(True)
            action.setChecked(key == target)
            action.blockSignals(False)

    def refresh_skin_menu(self) -> None:
        """按 ``skins/`` 当前实装情况重建「皮肤」子菜单项。

        包可能在程序运行期间被投放/删除，故菜单每次弹出前重建；勾选态由
        :meth:`set_skin_checked` 单独同步（重建后需重调）。
        """

        menu = self._skin_menu
        if menu is None:
            return
        current = self._cfg.skin_name
        menu.clear()
        self._skin_actions = {}
        group = QActionGroup(self._menu)
        group.setExclusive(True)
        self._skin_group = group

        from desktop_pet.ui.skin_renderer import available_skin_pack_entries

        items: list[tuple[str, str]] = [
            (C.SKIN_NAME_VECTOR, C.TRAY_SKIN_LABELS[C.SKIN_NAME_VECTOR]),
            (C.SKIN_NAME_AUTO, C.TRAY_SKIN_LABELS[C.SKIN_NAME_AUTO]),
        ]
        entries = available_skin_pack_entries()
        items.extend((name, label) for name, label, _tip in entries)
        for value, label in items:
            action = make_row_action(
                menu, label, kind="radio", accent=self._accent, min_width=182
            )
            action.setCheckable(True)
            action.setChecked(value == current)
            if value not in (C.SKIN_NAME_VECTOR, C.SKIN_NAME_AUTO):
                tip = next((tip for name, _label, tip in entries if name == value), "")
                if tip:
                    action.setToolTip(tip)
            action.triggered.connect(
                lambda _checked=False, v=value: self.skin_selected.emit(v)
            )
            group.addAction(action)
            self._skin_actions[value] = action


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
        if self._jp_review_limit_menu is not None:
            self._jp_review_limit_menu.setEnabled(enabled)
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

    def set_jp_review_limit_checked(self, value: int) -> None:
        """同步「复习上限」单选状态（不触发信号）。"""

        for option, action in self._jp_review_limit_actions.items():
            action.blockSignals(True)
            action.setChecked(option == int(value))
            action.blockSignals(False)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _add_group_label(self, menu: QMenu, text: str) -> None:
        """插入分组小标题行（原生托盘显示为置灰标题行，ShadowMenu 自绘小标题）。"""

        act = QWidgetAction(menu)
        act.setText(text)
        act.setEnabled(False)
        act.setData("group")
        act.setDefaultWidget(MenuGroupLabelWidget(act, text))
        menu.addAction(act)

    def _add_submenu_parent(
        self,
        parent_menu: QMenu,
        submenu: QMenu,
        text: str,
        icon: str,
        value: Callable[[], str] | None = None,
        swatch: Callable[[], tuple] | None = None,
    ) -> QWidgetAction:
        """以富行 widget 承载子菜单父行（行内当前值），并保留子菜单贴合几何。"""

        act = make_row_action(
            parent_menu, text, icon=icon, kind="submenu",
            value=value, swatch=swatch, accent=self._accent,
        )
        act.setMenu(submenu)
        submenu._parent_menu_override = parent_menu
        self._submenu_row_actions[submenu] = act
        return act

    def _build_menu(self) -> None:
        """构建右键菜单（富条目：头部 / 分组 / 行内值 / 迷你开关 / 徽标）。"""

        menu = self._menu
        w_jp = 250
        w_radio = 182

        # 头部身份区（仅 ShadowMenu 渲染；原生托盘为置灰标题行）
        head = QWidgetAction(menu)
        head.setText(f"小喵酱 v{__version__}")
        head.setEnabled(False)
        head.setData("header")
        head.setDefaultWidget(MenuHeaderWidget(
            head, name="小喵酱", version=f"v{__version__}",
            status=self._status, progress=self._progress, stops=self._stops,
        ))
        menu.addAction(head)

        self._action_restore = make_row_action(menu, "显示宠物", icon="pet")
        self._action_restore.triggered.connect(self.restore_requested.emit)
        self._action_minimize = make_row_action(menu, "最小化到托盘", icon="minimize")
        self._action_minimize.triggered.connect(self.minimize_requested.emit)

        self._add_group_label(menu, "互动")
        self._action_listen = make_row_action(
            menu, "监听键盘", icon="keyboard", kind="toggle", accent=self._accent
        )
        self._action_listen.setCheckable(True)
        self._action_listen.setChecked(bool(self._cfg.listen_enabled))
        self._action_listen.toggled.connect(self.listen_toggled.emit)

        self._action_bubble = make_row_action(
            menu, "气泡提示", icon="bubble", kind="toggle", accent=self._accent
        )
        self._action_bubble.setCheckable(True)
        self._action_bubble.setChecked(bool(self._cfg.bubble_enabled))
        self._action_bubble.toggled.connect(self.bubble_toggled.emit)

        self._action_bubble_text = make_row_action(menu, C.TRAY_MENU_BUBBLE_TEXT, icon="edit")
        self._action_bubble_text.triggered.connect(self.bubble_text_requested.emit)

        self._add_group_label(menu, "学习")
        # —— 日语学习子菜单 ——
        self._jp_menu = ShadowMenu(C.JP_MENU_TITLE, self._menu)
        jp = self._jp_menu
        self._action_jp = make_row_action(
            jp, C.JP_MENU_ENABLE, icon="book", kind="toggle",
            accent=self._accent, min_width=w_jp,
        )
        self._action_jp.setCheckable(True)
        self._action_jp.setChecked(bool(self._cfg.jp_enabled))
        self._action_jp.toggled.connect(self.jp_enabled_toggled.emit)

        self._action_jp_show_now = make_row_action(
            jp, C.JP_MENU_SHOW_NOW, icon="eye", min_width=w_jp
        )
        self._action_jp_show_now.triggered.connect(
            lambda _checked=False: self.jp_show_now_requested.emit()
        )
        jp.addSeparator()

        self._jp_level_menu = ShadowMenu(C.JP_MENU_LEVEL, self._menu)
        self._jp_level_group = QActionGroup(self._menu)
        self._jp_level_group.setExclusive(True)
        for level in C.JP_LEVELS:
            action = make_row_action(
                self._jp_level_menu, C.JP_LEVEL_LABELS.get(level, level),
                kind="radio", accent=self._accent, min_width=w_radio,
            )
            action.setCheckable(True)
            action.setChecked(level == self._cfg.jp_level)
            action.triggered.connect(
                lambda _checked=False, lv=level: self.jp_level_selected.emit(lv)
            )
            self._jp_level_group.addAction(action)
            self._jp_level_actions[level] = action
        self._add_submenu_parent(
            jp, self._jp_level_menu, C.JP_MENU_LEVEL, "level",
            value=lambda: self._cfg.jp_level,
        )

        self._jp_duration_menu = ShadowMenu(C.JP_MENU_DURATION, self._menu)
        self._jp_duration_group = QActionGroup(self._menu)
        self._jp_duration_group.setExclusive(True)
        for option in C.JP_BUBBLE_DURATION_OPTIONS:
            label = C.JP_BUBBLE_DURATION_LABELS.get(option, f"{option} 秒")
            action = make_row_action(
                self._jp_duration_menu, label, kind="radio",
                accent=self._accent, min_width=w_radio,
            )
            action.setCheckable(True)
            action.setChecked(option == self._cfg.jp_bubble_duration_s)
            action.triggered.connect(
                lambda _checked=False, opt=option: self.jp_duration_selected.emit(opt)
            )
            self._jp_duration_group.addAction(action)
            self._jp_duration_actions[option] = action
        self._add_submenu_parent(
            jp, self._jp_duration_menu, C.JP_MENU_DURATION, "clock",
            value=self._jp_duration_value,
        )

        self._jp_daily_limit_menu = ShadowMenu(C.JP_MENU_DAILY_LIMIT, self._menu)
        self._jp_daily_limit_group = QActionGroup(self._menu)
        self._jp_daily_limit_group.setExclusive(True)
        for option in C.JP_DAILY_LIMIT_OPTIONS:
            label = C.JP_DAILY_LIMIT_LABELS.get(option, f"{option} 个")
            action = make_row_action(
                self._jp_daily_limit_menu, label, kind="radio",
                accent=self._accent, min_width=w_radio,
            )
            action.setCheckable(True)
            action.setChecked(option == self._cfg.jp_daily_limit)
            action.triggered.connect(
                lambda _checked=False, opt=option: self.jp_daily_limit_selected.emit(opt)
            )
            self._jp_daily_limit_group.addAction(action)
            self._jp_daily_limit_actions[option] = action
        self._add_submenu_parent(
            jp, self._jp_daily_limit_menu, C.JP_MENU_DAILY_LIMIT, "calendar",
            value=self._jp_daily_value,
        )

        self._jp_review_limit_menu = ShadowMenu(C.JP_MENU_REVIEW_LIMIT, self._menu)
        self._jp_review_limit_group = QActionGroup(self._menu)
        self._jp_review_limit_group.setExclusive(True)
        for option in C.JP_REVIEW_DAILY_LIMIT_OPTIONS:
            label = C.JP_REVIEW_DAILY_LIMIT_LABELS.get(option, f"{option} 个")
            action = make_row_action(
                self._jp_review_limit_menu, label, kind="radio",
                accent=self._accent, min_width=w_radio,
            )
            action.setCheckable(True)
            action.setChecked(option == self._cfg.jp_review_daily_limit)
            action.triggered.connect(
                lambda _checked=False, opt=option: self.jp_review_limit_selected.emit(opt)
            )
            self._jp_review_limit_group.addAction(action)
            self._jp_review_limit_actions[option] = action
        self._add_submenu_parent(
            jp, self._jp_review_limit_menu, C.JP_MENU_REVIEW_LIMIT, "review",
            value=self._jp_review_value,
        )
        jp.addSeparator()

        self._action_jp_vocab = make_row_action(
            jp, C.JP_MENU_VOCAB, icon="bookmark", badge=self._vocab_badge, min_width=w_jp
        )
        self._action_jp_vocab.triggered.connect(
            lambda _checked=False: self.jp_vocab_requested.emit()
        )
        self._action_jp_mastered = make_row_action(
            jp, C.JP_MENU_MASTERED, icon="check", badge=self._mastered_badge, min_width=w_jp
        )
        self._action_jp_mastered.triggered.connect(
            lambda _checked=False: self.jp_mastered_requested.emit()
        )
        self._action_jp_log = make_row_action(jp, C.JP_MENU_LOG, icon="log", min_width=w_jp)
        self._action_jp_log.triggered.connect(
            lambda _checked=False: self.jp_log_requested.emit()
        )
        self._action_jp_stats = make_row_action(jp, C.JP_MENU_STATS, icon="chart", min_width=w_jp)
        self._action_jp_stats.triggered.connect(
            lambda _checked=False: self.jp_stats_requested.emit()
        )
        self._action_jp_import = make_row_action(jp, C.JP_MENU_IMPORT_BANK, icon="import", min_width=w_jp)
        self._action_jp_import.triggered.connect(
            lambda _checked=False: self.jp_import_bank_requested.emit()
        )
        self._add_submenu_parent(menu, jp, C.JP_MENU_TITLE, "book", value=self._jp_value)

        self._action_data = make_row_action(menu, C.TRAY_MENU_DATA, icon="database")
        self._action_data.triggered.connect(
            lambda _checked=False: self.data_manager_requested.emit()
        )
        self._action_update_check = make_row_action(
            menu, C.TRAY_MENU_CHECK_UPDATE, icon="refresh", badge=self._update_badge
        )
        self._action_update_check.triggered.connect(
            lambda _checked=False: self.update_check_requested.emit()
        )

        self._add_group_label(menu, "外观")
        scale_menu = ShadowMenu("大小", self._menu)
        self._scale_menu = scale_menu
        self._scale_group = QActionGroup(self._menu)
        self._scale_group.setExclusive(True)
        for value in C.SCALES:
            action = make_row_action(
                scale_menu, _SCALE_LABELS.get(value, f"{int(value * 100)}%"),
                kind="radio", accent=self._accent, min_width=w_radio,
            )
            action.setCheckable(True)
            action.setChecked(abs(value - float(self._cfg.scale)) < 1e-6)
            action.triggered.connect(lambda _checked=False, v=value: self.scale_selected.emit(v))
            self._scale_group.addAction(action)
            self._scale_actions[value] = action
        self._add_submenu_parent(menu, scale_menu, "大小", "scale", value=self._scale_value)

        self._theme_menu = ShadowMenu(C.TRAY_MENU_THEME, self._menu)
        self._theme_group = QActionGroup(self._menu)
        self._theme_group.setExclusive(True)
        for value in (C.AUTO_THEME, *C.THEMES):
            label = C.THEME_NAMES.get(value, value)
            action = make_row_action(
                self._theme_menu, label, kind="radio", accent=self._accent,
                min_width=w_radio,
                swatch=(None if value == C.AUTO_THEME else (lambda v=value: core_theme.theme_stops(v))),
            )
            action.setCheckable(True)
            action.setChecked(value == self._cfg.theme)
            action.triggered.connect(
                lambda _checked=False, v=value: self.theme_selected.emit(v)
            )
            self._theme_group.addAction(action)
            self._theme_actions[value] = action
        self._add_submenu_parent(
            menu, self._theme_menu, C.TRAY_MENU_THEME, "palette",
            value=self._theme_value, swatch=self._stops,
        )

        self._skin_menu = ShadowMenu(C.TRAY_MENU_SKIN, self._menu)
        self._skin_menu.aboutToShow.connect(self.refresh_skin_menu)
        self.refresh_skin_menu()
        self._add_submenu_parent(menu, self._skin_menu, C.TRAY_MENU_SKIN, "skin")

        self._add_group_label(menu, "偏好")
        self._action_autostart = make_row_action(
            menu, "开机自启", icon="power", kind="toggle", accent=self._accent
        )
        self._action_autostart.setCheckable(True)
        self._action_autostart.setChecked(bool(self._cfg.autostart))
        self._action_autostart.toggled.connect(self.autostart_toggled.emit)

        self._action_update_auto = make_row_action(
            menu, C.TRAY_MENU_UPDATE_AUTO, icon="clock", kind="toggle", accent=self._accent
        )
        self._action_update_auto.setCheckable(True)
        self._action_update_auto.setChecked(bool(self._cfg.update_check_enabled))
        self._action_update_auto.toggled.connect(self.update_auto_toggled.emit)

        self._action_reduce_motion = make_row_action(
            menu, C.TRAY_MENU_REDUCE_MOTION, icon="wind", kind="toggle", accent=self._accent
        )
        self._action_reduce_motion.setCheckable(True)
        self._action_reduce_motion.setChecked(bool(self._cfg.reduce_motion))
        self._action_reduce_motion.setToolTip(C.TRAY_MENU_REDUCE_MOTION_TIP)
        self._action_reduce_motion.toggled.connect(self.reduce_motion_toggled.emit)

        menu.addSeparator()
        self._action_quit = make_row_action(menu, "退出小喵酱", icon="quit", danger=True)
        self._action_quit.triggered.connect(self.quit_requested.emit)

        self._apply_menu_icons()

    def _apply_menu_icons(self) -> None:
        """为菜单逐行挂程序化矢量图标（右键菜单精致化）；退出染 destructive 红。

        图标在两条路径都可见：原生托盘（macOS NSMenu）与宠物窗口右键
        （ShadowMenu 自绘）。行高 / 阴影 / 圆角高亮等仅后者生效（平台边界）。

        **可勾选开关不挂图标**：Qt 在动作带图标时会丢弃勾选标记，开关状态将不可见；
        故开关（监听 / 气泡 / 自启 / 自动更新 / 减少动效 / 日语开关）保留原生勾选，
        命令与子菜单父行才挂图标。单选子项同样保留原生勾选，避免双标记拥挤。
        """

        normal = C.SEMANTIC_COLORS["text_secondary"]
        pairs: list[tuple[QAction | QMenu, str]] = [
            (self._action_restore, "pet"),
            (self._action_minimize, "minimize"),
            (self._action_bubble_text, "edit"),
            (self._jp_menu, "book"),
            (self._action_jp_show_now, "eye"),
            (self._jp_level_menu, "level"),
            (self._jp_duration_menu, "clock"),
            (self._jp_daily_limit_menu, "calendar"),
            (self._jp_review_limit_menu, "review"),
            (self._action_jp_vocab, "bookmark"),
            (self._action_jp_mastered, "check"),
            (self._action_jp_log, "log"),
            (self._action_jp_stats, "chart"),
            (self._action_jp_import, "import"),
            (self._action_data, "database"),
            (self._action_update_check, "refresh"),
            (self._scale_menu, "scale"),
            (self._theme_menu, "palette"),
            (self._skin_menu, "skin"),
        ]
        for obj, name in pairs:
            if obj is None:
                continue
            icon = menu_icon(name, normal)
            obj.setIcon(icon)
            # 子菜单父行在 ShadowMenu 里是富行 widget（QWidgetAction），原生托盘
            # 读的是该 widgetAction 的图标；submenu 自身图标另供 menuAction 语义。
            if isinstance(obj, QMenu):
                row = self._submenu_row_actions.get(obj)
                if row is not None:
                    row.setIcon(icon)
        self._action_quit.setIcon(menu_icon("quit", C.SEMANTIC_COLORS["destructive"]))

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """托盘图标点击：双击恢复窗口，单击弹出菜单。"""

        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.restore_requested.emit()
        elif reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._menu.popup(self._menu.cursor().pos())


__all__ = ["TrayController"]
