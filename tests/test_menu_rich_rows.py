"""富条目菜单（预览工件 menu-redesign.canvas.tsx 的 Qt 落地）回归测试。

守护「补齐到与预览一致」的核心不变式：

- 新增富条目标量（行高 / 行圆角 / 字号 / 面板宽 / 头部高 / 分组高 / 开关尺寸 /
  动效时长）为正且已同步 ``__all__``；关键值钉死导出规格（rowH 30 / itemR 5 /
  font 12.5 / motion 100ms）。
- ``make_row_action``：QWidgetAction 入菜单、语义落在 QAction、富行 widget
  尺寸取 MENU_ROW_H_PX、鼠标事件透明（交回 QMenu 原生导航）。
- 头部身份区 / 分组小标题：data 标记、置灰不可点、尺寸取 token。
- 迷你开关：开关行仍 checkable 且**不 setIcon**（原生托盘勾选不丢），ON/OFF
  像素互异；单选行勾选态 likewise 反映到像素。
- 行内值 / 徽标 / 红点：provider 实时读取——配置或数据变化后重绘即变，无需
  逐 widget 同步；ShadowMenu.paintEvent 向富行 widget 传播 update。
- 子菜单父行经 setMenu 挂载后，``_parent_menu_override`` 保住贴合几何。
- 入场动效：默认 MENU_MOTION_MS；reduce_motion 一键直通 0（全部菜单）。

全部使用 ``QT_QPA_PLATFORM=offscreen``（conftest 强制）。
"""

from __future__ import annotations

import hashlib

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidgetAction

from desktop_pet import __version__
from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig
from desktop_pet.ui.menu_rows import (
    MenuGroupLabelWidget,
    MenuHeaderWidget,
    MenuRowWidget,
    make_row_action,
)
from desktop_pet.ui.menu_shadow import ShadowMenu
from desktop_pet.ui.tray import TrayController

#: 本次新增的富条目标量（不动五张 token 字典键集合红线）。
_RICH_SCALARS = (
    "MENU_ROW_H_PX",
    "MENU_ITEM_RADIUS_PX",
    "MENU_FONT_PX",
    "MENU_WIDTH_PX",
    "MENU_HEADER_H_PX",
    "MENU_GROUP_LABEL_H_PX",
    "MENU_SWITCH_W_PX",
    "MENU_SWITCH_H_PX",
    "MENU_MOTION_MS",
)


def _sig(image) -> str:
    return hashlib.sha256(bytes(image.constBits())).hexdigest()


@pytest.fixture(autouse=True, scope="module")
def _warm_font_aliases(qapp):
    """离屏首绘会触发字体别名填充（耗时且改变字形）——先暖机，防像素比对抖动。"""

    from PySide6.QtWidgets import QLabel

    label = QLabel("暖机")
    label.resize(64, 24)
    label.grab()


def _render(widget) -> str:
    # 固定宽度渲染：QMenu 布局会把行 widget 吸附到菜单宽，独立 resize 不稳定。
    widget.resize(C.MENU_WIDTH_PX, widget.sizeHint().height())
    return _sig(widget.grab().toImage())


def _row_widget(action: QWidgetAction) -> MenuRowWidget:
    widget = action.defaultWidget()
    assert isinstance(widget, MenuRowWidget)
    return widget


# --------------------------------------------------------------------------- #
# 1. 新常量：正数 / __all__ / 导出规格钉死
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", _RICH_SCALARS)
def test_rich_scalars_positive_and_exported(name: str) -> None:
    value = getattr(C, name)
    assert isinstance(value, (int, float)) and value > 0, f"{name} 非正数：{value!r}"
    assert name in C.__all__, f"{name} 未同步进 __all__"


def test_rich_scalars_match_exported_spec() -> None:
    """关键值钉死 menu-redesign-params.json 的导出规格，防漂移。"""

    assert C.MENU_ROW_H_PX == 30
    assert C.MENU_ITEM_RADIUS_PX == 5
    assert C.MENU_FONT_PX == 12.5
    assert C.MENU_MOTION_MS == 100
    assert C.MENU_SWITCH_W_PX > C.MENU_SWITCH_H_PX, "开关应为横向胶囊"
    assert C.MENU_SWITCH_H_PX >= 16, "开关高度须容下 12px 旋钮 + 上下 2px 边距"


# --------------------------------------------------------------------------- #
# 2. make_row_action 基础契约
# --------------------------------------------------------------------------- #
def test_make_row_action_adds_to_menu_with_semantics(qtbot) -> None:
    menu = ShadowMenu()
    qtbot.addWidget(menu)
    act = make_row_action(menu, "测试条目", icon="pet", min_width=200)

    assert menu.actions()[-1] is act, "工厂未把动作挂进菜单"
    assert isinstance(act, QWidgetAction)
    assert act.text() == "测试条目"
    widget = _row_widget(act)
    assert widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents), (
        "行 widget 必须鼠标透明，事件交回 QMenu 保留原生导航"
    )
    hint = widget.sizeHint()
    assert hint.height() == C.MENU_ROW_H_PX
    assert hint.width() >= 200, "min_width 未生效"


# --------------------------------------------------------------------------- #
# 3. 头部身份区 / 分组小标题
# --------------------------------------------------------------------------- #
def test_tray_header_is_first_disabled_identity_row(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    head = tray.menu.actions()[0]
    assert head.data() == "header"
    assert not head.isEnabled(), "头部不可点击"
    assert __version__ in head.text(), "原生托盘回退文案应含版本号"
    widget = head.defaultWidget()
    assert isinstance(widget, MenuHeaderWidget)
    assert widget.sizeHint().width() == C.MENU_WIDTH_PX
    assert widget.sizeHint().height() == C.MENU_HEADER_H_PX + 7
    assert _render(widget), "头部渲染为空"


def test_tray_group_labels_present_in_order(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    groups = [a for a in tray.menu.actions() if a.data() == "group"]
    assert [a.text() for a in groups] == ["互动", "学习", "外观", "偏好"]
    for act in groups:
        assert not act.isEnabled(), "分组小标题不可点击"
        assert isinstance(act.defaultWidget(), MenuGroupLabelWidget)
        assert act.defaultWidget().sizeHint().height() == C.MENU_GROUP_LABEL_H_PX


def test_header_status_and_progress_follow_config(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig(jp_enabled=True, jp_daily_limit=15))
    tray.set_data_providers(today_words=lambda: 8)
    on, text = tray._status()
    assert on and "8/15" in text
    assert tray._progress() == pytest.approx(8 / 15)

    tray._cfg.jp_enabled = False
    on, text = tray._status()
    assert not on and "关闭" in text


# --------------------------------------------------------------------------- #
# 4. 迷你开关 / 单选：勾选态反映到像素，QAction 保持无图标
# --------------------------------------------------------------------------- #
def test_toggle_rows_render_switch_on_off_distinct(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    widget = _row_widget(tray._action_listen)
    assert widget._kind == "toggle"

    tray._action_listen.setChecked(False)
    off = _render(widget)
    tray._action_listen.setChecked(True)
    on = _render(widget)
    assert off != on, "开关 ON/OFF 像素相同——迷你开关未画或状态未读"


def test_radio_rows_render_check_only_when_selected(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    action = tray._jp_level_actions["N5"]
    widget = _row_widget(action)
    assert widget._kind == "radio"

    checked = _render(widget)
    tray.set_jp_level_checked("N1")
    unchecked = _render(widget)
    assert checked != unchecked, "单选勾选态未反映到像素"


# --------------------------------------------------------------------------- #
# 5. 行内值 / 徽标 / 红点：provider 实时读取
# --------------------------------------------------------------------------- #
def test_inline_values_reflect_config(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig(jp_enabled=True))
    assert tray._jp_value() == "N5 · 15 词/日"
    assert tray._scale_value() == "100%"
    assert tray._theme_value() == C.THEME_NAMES[C.DEFAULT_THEME]

    tray._cfg.jp_enabled = False
    assert tray._jp_value() == "已关闭"
    tray._cfg.scale = 1.2
    assert tray._scale_value() == "120%"


def test_submenu_parent_row_rerenders_on_config_change(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    widget = _row_widget(tray._submenu_row_actions[tray._scale_menu])
    before = _render(widget)
    tray._cfg.scale = 1.2
    after = _render(widget)
    assert before != after, "行内值变化后重绘未变——provider 未在 paint 时读取"


def test_vocab_and_mastered_badges_read_providers_live(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    widget = _row_widget(tray._action_jp_vocab)
    empty = _render(widget)

    tray.set_data_providers(vocab_count=lambda: 23, mastered_count=lambda: 128)
    assert tray._vocab_badge() == "23"
    assert tray._mastered_badge() == "128"
    assert _render(widget) != empty, "徽标注入后重绘未变"
    assert _render(_row_widget(tray._action_jp_mastered)) != empty


def test_update_red_dot_follows_flag(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    widget = _row_widget(tray._action_update_check)
    assert tray._update_badge() is None
    clean = _render(widget)

    tray.set_update_available(True)
    assert tray._update_badge() == "dot"
    dotted = _render(widget)
    assert dotted != clean, "红点未画"

    tray.set_update_available(False)
    assert _render(widget) == clean, "红点状态回落未还原"


def test_quit_row_paints_destructive_red(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    widget = _row_widget(tray._action_quit)
    assert widget._danger is True
    widget.resize(C.MENU_WIDTH_PX, widget.sizeHint().height())
    image = widget.grab().toImage()
    assert any(
        image.pixelColor(x, y).alpha() > 0
        and image.pixelColor(x, y).red() > 150
        and image.pixelColor(x, y).red() > image.pixelColor(x, y).green() + 40
        for y in range(image.height())
        for x in range(image.width())
    ), "退出行未染 destructive 红"


# --------------------------------------------------------------------------- #
# 6. 刷新传播 / 子菜单贴合 / 动效
# --------------------------------------------------------------------------- #
def test_shadow_menu_paint_propagates_update_to_rich_widgets(qtbot, monkeypatch) -> None:
    tray = TrayController(QIcon(), AppConfig())
    menu = tray.menu
    qtbot.addWidget(menu)
    widget = _row_widget(tray._action_restore)
    calls: list[int] = []
    monkeypatch.setattr(widget, "update", lambda *a: calls.append(1))
    menu.grab()
    assert calls, "ShadowMenu.paintEvent 未向富行 widget 传播 update"


def test_submenu_parent_override_preserves_visual_parent(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    assert tray._jp_menu._visual_parent_menu() is tray.menu
    assert tray._jp_level_menu._visual_parent_menu() is tray._jp_menu
    assert tray._jp_duration_menu._visual_parent_menu() is tray._jp_menu
    assert tray._jp_daily_limit_menu._visual_parent_menu() is tray._jp_menu
    assert tray._jp_review_limit_menu._visual_parent_menu() is tray._jp_menu
    assert tray._scale_menu._visual_parent_menu() is tray.menu
    assert tray._theme_menu._visual_parent_menu() is tray.menu
    assert tray._skin_menu._visual_parent_menu() is tray.menu


def test_enter_motion_defaults_to_token_and_animates(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    for menu in tray._all_menus:
        assert isinstance(menu, ShadowMenu)
        assert menu.motion_ms == C.MENU_MOTION_MS

    menu = tray.menu
    qtbot.addWidget(menu)
    menu.motion_ms = 5000  # 拉长避免离屏时序抖动
    menu.popup(QPoint(60, 60))
    qtbot.waitUntil(menu.isVisible)
    assert menu._anim is not None, "入场淡入动画未启动"
    menu.close()


def test_reduce_motion_zeroes_motion_on_all_menus(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    # 真实链路：controller 先写 cfg 再调 setter（tray 与 controller 共享 cfg 对象）。
    tray._cfg.reduce_motion = True
    tray.set_reduce_motion_checked(True)
    for menu in tray._all_menus:
        assert menu.motion_ms == 0, "reduce_motion 未直通全部菜单动效"

    menu = tray.menu
    qtbot.addWidget(menu)
    menu.popup(QPoint(60, 60))
    qtbot.waitUntil(menu.isVisible)
    assert menu._anim is None, "reduce_motion 下不应启动动画"
    menu.close()

    tray._cfg.reduce_motion = False
    tray.set_reduce_motion_checked(False)
    assert all(m.motion_ms == C.MENU_MOTION_MS for m in tray._all_menus)