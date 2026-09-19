"""托盘「主题」子菜单回归测试（阶段 A4）。

守护链路：菜单单选态 ↔ ``AppConfig.theme`` ↔ ``PetRenderer`` 皮肤 ↔ 托盘勾选。
覆盖：

- ui 层：信号存在；「主题」子菜单含「自动」+ 7 套皮肤，均 checkable 且置入**单选**组；
  初值来自 ``cfg.theme``；触发即发信号；``set_theme_checked`` 同步勾选但**不回流**信号；
  单选互斥（选一个自动取消其它）。
- app 层：``_on_theme_selected`` 写配置 + 落地 + 应用渲染器皮肤 + 同步托盘勾选。

全部使用 ``QT_QPA_PLATFORM=offscreen``。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig, ConfigStore
from desktop_pet.ui.tray import TrayController

_EXPECTED_KEYS = ["auto", "default", "spring", "summer", "autumn", "winter",
                  "spring_festival"]


# --------------------------------------------------------------------------- #
# 1. ui 层：菜单结构与信号
# --------------------------------------------------------------------------- #
def test_tray_exposes_theme_signal_and_menu(qtbot) -> None:
    """信号存在；「主题」子菜单存在。"""

    tray = TrayController(QIcon(), AppConfig())
    assert hasattr(tray, "theme_selected")
    assert tray._theme_menu is not None
    assert tray._theme_menu.title() == C.TRAY_MENU_THEME == "主题"


def test_theme_menu_has_auto_plus_six_skins(qtbot) -> None:
    """子菜单含「自动」+ 6 套皮肤，共 7 项，全部 checkable。"""

    tray = TrayController(QIcon(), AppConfig())
    actions = tray._theme_menu.actions()
    assert len(actions) == 7
    assert set(tray._theme_actions) == set(_EXPECTED_KEYS)
    for key, action in tray._theme_actions.items():
        assert action.isCheckable(), f"{key} 未设 checkable"
    assert tray._theme_actions["auto"].text() == "自动"


def test_theme_actions_are_exclusive_group(qtbot) -> None:
    """7 个项共属一个 **exclusive** 的 ``QActionGroup``。"""

    from PySide6.QtGui import QActionGroup

    tray = TrayController(QIcon(), AppConfig())
    group = tray._theme_group
    assert isinstance(group, QActionGroup)
    assert group.isExclusive() is True
    assert len(group.actions()) == 7


def test_theme_default_checked_follows_config(qtbot) -> None:
    """勾选初值来自 ``cfg.theme``（默认 default / 显式 winter 两向）。"""

    dft = TrayController(QIcon(), AppConfig())
    assert dft._theme_actions["default"].isChecked() is True

    winter = TrayController(QIcon(), AppConfig(theme="winter"))
    assert winter._theme_actions["winter"].isChecked() is True
    assert winter._theme_actions["default"].isChecked() is False


def test_theme_action_emits_signal_with_value(qtbot) -> None:
    """点击皮肤项 → 信号带正确的取值字符串。"""

    tray = TrayController(QIcon(), AppConfig())
    captured: list[str] = []
    tray.theme_selected.connect(captured.append)

    tray._theme_actions["autumn"].trigger()
    assert captured == ["autumn"], f"期望 ['autumn']，实际 {captured}"

    tray._theme_actions["auto"].trigger()
    assert captured == ["autumn", "auto"], f"实际 {captured}"


def test_theme_selection_is_mutually_exclusive(qtbot) -> None:
    """单选互斥：选一个自动取消其它。"""

    tray = TrayController(QIcon(), AppConfig())
    tray._theme_actions["summer"].trigger()
    assert tray._theme_actions["summer"].isChecked() is True
    assert tray._theme_actions["default"].isChecked() is False

    tray._theme_actions["spring_festival"].trigger()
    assert tray._theme_actions["spring_festival"].isChecked() is True
    assert tray._theme_actions["summer"].isChecked() is False


def test_set_theme_checked_is_silent(qtbot) -> None:
    """``set_theme_checked`` 同步勾选态但**不回流**信号（防死循环）。"""

    tray = TrayController(QIcon(), AppConfig())
    captured: list[str] = []
    tray.theme_selected.connect(captured.append)

    tray.set_theme_checked("spring")
    assert tray._theme_actions["spring"].isChecked() is True
    assert tray._theme_actions["default"].isChecked() is False
    assert captured == [], f"同步回调不应触发信号，实际 {captured}"


def test_theme_menu_is_attached_to_main_menu(qtbot) -> None:
    """「主题」子菜单确实挂进了托盘主菜单。"""

    tray = TrayController(QIcon(), AppConfig())
    titles = [a.text() for a in tray.menu.actions() if a.menu() is not None]
    assert C.TRAY_MENU_THEME in titles, f"主菜单未见「主题」子菜单：{titles}"


# --------------------------------------------------------------------------- #
# 2. app 层：切换落地 + 应用渲染器 + 同步勾选
# --------------------------------------------------------------------------- #
def _make_controller(tmp_path: Path, theme: str = "default"):
    from desktop_pet.app.controller import PetAppController

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(AppConfig(listen_enabled=False, theme=theme))
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    return PetAppController(app, store), store


def test_on_theme_selected_applies_and_persists(qtbot, tmp_path: Path) -> None:
    """切换皮肤：写 cfg + 落地 + 渲染器皮肤变化 + 托盘勾选同步。"""

    controller, store = _make_controller(tmp_path)
    try:
        controller.start()
        # 默认皮肤生效
        assert controller._cfg.theme == "default"
        assert controller._renderer.theme_stops() is C.THEMES["default"]

        controller._on_theme_selected("autumn")

        assert controller._cfg.theme == "autumn"
        assert controller._renderer.theme_stops() is C.THEMES["autumn"]
        assert controller._tray._theme_actions["autumn"].isChecked() is True
        assert store.load().theme == "autumn", "主题未落地到配置文件"
    finally:
        controller.shutdown()
        QApplication.instance().processEvents()


def test_on_theme_selected_rejects_illegal_value(qtbot, tmp_path: Path) -> None:
    """非法主题取值被忽略（不写配置、不崩溃）。"""

    controller, _store = _make_controller(tmp_path)
    try:
        controller.start()
        controller._on_theme_selected("banana")
        assert controller._cfg.theme == "default"
    finally:
        controller.shutdown()
        QApplication.instance().processEvents()


def test_auto_theme_resolves_by_month_at_start(qtbot, tmp_path: Path) -> None:
    """``auto`` 档启动时按当前月份解析（渲染器皮肤属于四季之一）。"""

    controller, _store = _make_controller(tmp_path, theme="auto")
    try:
        controller.start()
        assert controller._cfg.theme == "auto"
        # 生效皮肤必属四季之一（auto 映射结果），且托盘勾选停在「自动」
        assert controller._current_theme in {"spring", "summer", "autumn", "winter"}
        assert controller._tray._theme_actions["auto"].isChecked() is True
    finally:
        controller.shutdown()
        QApplication.instance().processEvents()


def test_tray_theme_click_reaches_controller(qtbot, tmp_path: Path) -> None:
    """端到端：真实点击托盘皮肤项 → 经信号 → 配置与渲染器都变。"""

    controller, store = _make_controller(tmp_path)
    try:
        controller.start()
        controller._tray._theme_actions["winter"].trigger()
        assert controller._cfg.theme == "winter"
        assert controller._renderer.theme_stops() is C.THEMES["winter"]
        assert store.load().theme == "winter"
    finally:
        controller.shutdown()
        QApplication.instance().processEvents()
