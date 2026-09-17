"""托盘「减少动效」菜单项回归测试（UI 视觉升级增量）。

守护链路：菜单勾选态 ↔ ``AppConfig.reduce_motion`` ↔ 已打开业务窗口的
``set_reduce_motion``。三者必须联动，否则用户在托盘里拨了开关却看不到任何变化。

覆盖：

- ui 层：菜单项存在且 checkable、初值来自配置、触发即发信号、同步不回流信号。
- app 层：``_on_reduce_motion_toggled`` 写配置 + 落地 + 同步托盘 + 同步已开窗口；
  未创建的窗口不报错（``show`` 时会再读配置）。

全部使用 ``QT_QPA_PLATFORM=offscreen``，不依赖真实窗口显示。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig, ConfigStore
from desktop_pet.ui.tray import TrayController


def _menu_labels(tray: TrayController) -> list[str]:
    """菜单顶层条目文案（分隔符/子菜单用空串占位，保持顺序信息可选）。"""

    labels: list[str] = []
    for action in tray.menu.actions():
        labels.append(action.text() if not action.isSeparator() else "")
    return labels


# --------------------------------------------------------------------------- #
# 1. ui 层：菜单结构与信号
# --------------------------------------------------------------------------- #
def test_tray_exposes_reduce_motion_signal_and_action(qtbot) -> None:
    """信号存在；菜单项存在、可勾选、带提示文案。"""

    tray = TrayController(QIcon(), AppConfig())

    assert hasattr(tray, "reduce_motion_toggled"), "缺少 reduce_motion_toggled 信号"
    action = tray._action_reduce_motion
    assert action is not None, "未创建 _action_reduce_motion"
    assert action.text() == C.TRAY_MENU_REDUCE_MOTION
    assert action.text() == "减少动效"
    assert action.isCheckable() is True
    assert action.toolTip() == C.TRAY_MENU_REDUCE_MOTION_TIP


def test_tray_reduce_motion_initial_checked_follows_config(qtbot) -> None:
    """勾选态初值来自 ``AppConfig.reduce_motion``（默认 False / 显式 True 两向）。"""

    off = TrayController(QIcon(), AppConfig())
    assert off._action_reduce_motion.isChecked() is False

    on = TrayController(QIcon(), AppConfig(reduce_motion=True))
    assert on._action_reduce_motion.isChecked() is True


def test_tray_reduce_motion_toggled_emits(qtbot) -> None:
    """点击菜单项 → 信号带正确布尔值；再点一次回到 False。"""

    tray = TrayController(QIcon(), AppConfig())
    captured: list[bool] = []
    tray.reduce_motion_toggled.connect(captured.append)

    tray._action_reduce_motion.trigger()
    assert captured == [True], f"期望 [True]，实际 {captured}"

    tray._action_reduce_motion.trigger()
    assert captured == [True, False], f"期望 [True, False]，实际 {captured}"


def test_tray_set_reduce_motion_checked_is_silent(qtbot) -> None:
    """``set_reduce_motion_checked`` 同步勾选态但**不回流**信号（防死循环）。"""

    tray = TrayController(QIcon(), AppConfig())
    captured: list[bool] = []
    tray.reduce_motion_toggled.connect(captured.append)

    tray.set_reduce_motion_checked(True)
    assert tray._action_reduce_motion.isChecked() is True
    assert captured == [], f"同步回调不应触发信号，实际 {captured}"


def test_tray_reduce_motion_action_is_in_menu(qtbot) -> None:
    """菜单里确实挂上了「减少动效」，且位于「开机自启」之后、「退出」之前。"""

    tray = TrayController(QIcon(), AppConfig())
    labels = _menu_labels(tray)

    assert C.TRAY_MENU_REDUCE_MOTION in labels, f"菜单顶层未见该条目：{labels}"
    assert labels.index("开机自启") < labels.index(C.TRAY_MENU_REDUCE_MOTION)
    assert labels.index(C.TRAY_MENU_REDUCE_MOTION) < labels.index("退出")


# --------------------------------------------------------------------------- #
# 2. app 层：开关落地 + 同步已开窗口
# --------------------------------------------------------------------------- #
# 说明：这里**故意不**断言「controller 启动时把 cfg 回填到托盘勾选态」。
# 那行代码（``_start`` 中的 ``set_reduce_motion_checked``）与
# ``TrayController.__init__`` 的初值读取同源（同一个 AppConfig 对象），
# 删除它不改变任何可观测状态 —— 断言它会是一条恒绿假测试。
# 初值行为由上方 ``test_tray_reduce_motion_initial_checked_follows_config`` 守护。
# --------------------------------------------------------------------------- #
def test_on_reduce_motion_toggled_persists_and_syncs_open_windows(
    qtbot, tmp_path: Path
) -> None:
    """切换开关：写配置 + 落地 + 同步托盘 + 同步**已打开**的窗口（无需重开）。"""

    from desktop_pet.app.controller import PetAppController

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(AppConfig(listen_enabled=False, reduce_motion=False))

    app = QApplication.instance()
    assert isinstance(app, QApplication)

    controller = PetAppController(app, store)
    try:
        controller.start()
        assert controller._cfg.reduce_motion is False

        # 打开生词本 → 窗口按当时配置注入 False
        controller._on_jp_vocab()
        window = controller._vocab_window
        assert window is not None, "生词本窗口未创建（用例前提不成立）"
        assert window._reduce_motion is False

        # 用户拨动托盘开关
        controller._on_reduce_motion_toggled(True)

        assert controller._cfg.reduce_motion is True
        assert window._reduce_motion is True, "已打开的窗口未同步「减少动效」"
        assert controller._tray._action_reduce_motion.isChecked() is True
        assert store.load().reduce_motion is True, "开关未落地到配置文件"

        # 再关掉：同样要回流到已开窗口
        controller._on_reduce_motion_toggled(False)
        assert controller._cfg.reduce_motion is False
        assert window._reduce_motion is False
        assert store.load().reduce_motion is False
    finally:
        controller.shutdown()
        app.processEvents()


def test_on_reduce_motion_toggled_without_windows_is_safe(qtbot, tmp_path: Path) -> None:
    """三个窗口都没创建过时切换开关不得抛异常（``show`` 时会再读配置）。"""

    from desktop_pet.app.controller import PetAppController

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(AppConfig(listen_enabled=False))

    app = QApplication.instance()
    assert isinstance(app, QApplication)

    controller = PetAppController(app, store)
    try:
        controller.start()
        assert controller._vocab_window is None
        assert controller._log_window is None
        assert controller._detail_window is None

        controller._on_reduce_motion_toggled(True)
        assert controller._cfg.reduce_motion is True
    finally:
        controller.shutdown()
        app.processEvents()


def test_tray_toggle_reaches_controller_through_signal(qtbot, tmp_path: Path) -> None:
    """端到端：真实点击托盘菜单项 → 经过信号 → 配置与窗口都变。"""

    from desktop_pet.app.controller import PetAppController

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(AppConfig(listen_enabled=False, reduce_motion=False))

    app = QApplication.instance()
    assert isinstance(app, QApplication)

    controller = PetAppController(app, store)
    try:
        controller.start()
        controller._on_jp_log()
        window = controller._log_window
        assert window is not None, "学习记录窗口未创建（用例前提不成立）"
        assert window._reduce_motion is False

        controller._tray._action_reduce_motion.trigger()

        assert controller._cfg.reduce_motion is True
        assert window._reduce_motion is True, "托盘点击未贯通到窗口"
    finally:
        controller.shutdown()
        app.processEvents()
