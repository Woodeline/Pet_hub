"""右键菜单精致化（行图标 + 柔和阴影 + 统一行高）回归测试。

守护本次「更新 Mac app」落地的菜单重设计不变式：

- 新增菜单标量常量（面板圆角 / 图标边长 / 高亮内缩 / 行内容最小高）为正整数且
  已同步 ``__all__``；阴影留白 BAND 足以容纳模糊尾部 + 下沉（不硬裁软阴影）。
- ``menu_icon`` 独立注册表齐全、逐图标非空且互异、未知名抛错、默认尺寸取 token、
  自定义色生效、全程零落盘素材；**不**并入 ``ICON_NAMES``（按钮六图标清单另守）。
- 托盘接线：命令 / 子菜单父行挂图标；**可勾选开关不挂图标**（Qt 带图标会丢勾选
  标记，开关状态必须靠原生勾选可见）；单选子项 likewise 无图标；退出染 destructive 红。
- 行高统一：勾选行与图标行经 ``min-height`` 对齐，菜单不参差。

全部使用 ``QT_QPA_PLATFORM=offscreen``（conftest 强制）。
"""

from __future__ import annotations

import hashlib

import pytest
from PySide6.QtCore import QPoint
from PySide6.QtGui import QIcon

from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig
from desktop_pet.ui import icon_factory
from desktop_pet.ui.theme import build_menu_qss
from desktop_pet.ui.tray import TrayController

#: 本次新增的独立标量（不动五张 token 字典键集合红线）。
_NEW_SCALARS = (
    "MENU_PANEL_RADIUS_PX",
    "MENU_ICON_PX",
    "MENU_ITEM_INSET_PX",
    "MENU_ROW_MIN_H_PX",
)

_IMAGE_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".ico", ".svg", ".webp",
    ".tif", ".tiff", ".qrc", ".xpm",
}


def _opaque(image) -> bool:
    return any(
        image.pixelColor(x, y).alpha() > 0
        for y in range(image.height())
        for x in range(image.width())
    )


def _sig(image) -> str:
    return hashlib.sha256(bytes(image.constBits())).hexdigest()


# --------------------------------------------------------------------------- #
# 1. 新常量：正整数 / __all__ / 阴影几何自洽
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", _NEW_SCALARS)
def test_new_menu_scalars_positive_and_exported(name: str) -> None:
    value = getattr(C, name)
    assert isinstance(value, int) and value > 0, f"{name} 非正整数：{value!r}"
    assert name in C.__all__, f"{name} 未同步进 __all__"


def test_shadow_band_fits_blur_tail_and_offset() -> None:
    """BAND 必须 ≥ 模糊外溢 margin（+ 下沉），否则软阴影被窗口边缘硬裁。"""

    margin = C.MENU_SHADOW_BLUR_PX // 2 + 2
    assert C.MENU_SHADOW_BAND_PX >= margin, "留白不足以容纳模糊尾部"
    assert C.MENU_SHADOW_BAND_PX >= margin + C.MENU_SHADOW_OFFSET_Y, (
        "留白不足以容纳下沉后的模糊尾部（下方会被硬裁）"
    )


def test_menu_qss_uniform_row_min_height() -> None:
    """QSS 用 MENU_ROW_MIN_H_PX 统一勾选行 / 图标行行高。"""

    assert f"min-height: {C.MENU_ROW_MIN_H_PX}px" in build_menu_qss()


# --------------------------------------------------------------------------- #
# 2. menu_icon 工厂
# --------------------------------------------------------------------------- #
def test_menu_icon_names_complete() -> None:
    assert icon_factory.MENU_ICON_NAMES == (
        "pet", "minimize", "edit", "book", "database",
        "refresh", "scale", "palette", "skin", "quit",
        "eye", "bookmark", "check", "log", "calendar", "review", "level",
        "chart", "import", "clock",
        "keyboard", "bubble", "power", "wind",
    )
    # 与按钮六图标注册表互不污染（菜单图标集独立扩张）
    assert set(icon_factory.MENU_ICON_NAMES).isdisjoint(icon_factory.ICON_NAMES)
    assert icon_factory.ICON_NAMES == (
        "close", "retry", "remove", "trash", "speaker", "pencil",
    )


@pytest.mark.parametrize("name", icon_factory.MENU_ICON_NAMES)
def test_menu_icon_renders_nonempty(qapp, name: str) -> None:
    icon = icon_factory.menu_icon(name)
    assert not icon.isNull(), f"{name} 返回空图标"
    pm = icon.pixmap(C.MENU_ICON_PX, C.MENU_ICON_PX)
    assert (pm.width(), pm.height()) == (C.MENU_ICON_PX, C.MENU_ICON_PX)
    assert _opaque(pm.toImage()), f"{name} 是空白图"


def test_menu_icons_are_visually_distinct(qapp) -> None:
    sigs = {
        name: _sig(icon_factory.menu_icon(name).pixmap(C.MENU_ICON_PX, C.MENU_ICON_PX).toImage())
        for name in icon_factory.MENU_ICON_NAMES
    }
    assert len(set(sigs.values())) == len(icon_factory.MENU_ICON_NAMES), "存在重复菜单图标"


def test_menu_icon_unknown_name_raises(qapp) -> None:
    with pytest.raises(ValueError):
        icon_factory.menu_icon("nope")


def test_menu_icon_default_size_is_token(qapp) -> None:
    sizes = {(s.width(), s.height()) for s in icon_factory.menu_icon("pet").availableSizes()}
    assert (C.MENU_ICON_PX, C.MENU_ICON_PX) in sizes


def test_menu_icon_custom_color_changes_pixels(qapp) -> None:
    default = _sig(icon_factory.menu_icon("quit").pixmap(32, 32).toImage())
    red_img = icon_factory.menu_icon(
        "quit", color=C.SEMANTIC_COLORS["destructive"], px=32
    ).pixmap(32, 32).toImage()
    assert default != _sig(red_img), "自定义色未改变像素"
    assert any(
        red_img.pixelColor(x, y).alpha() > 0 and red_img.pixelColor(x, y).red() > 150
        for y in range(32) for x in range(32)
    ), "destructive 红未反映到像素"


def test_menu_icon_rendering_creates_no_image_assets(qapp, project_root) -> None:
    for name in icon_factory.MENU_ICON_NAMES:
        icon_factory.menu_icon(name, px=32)
    offenders = [
        str(p.relative_to(project_root))
        for p in project_root.rglob("*")
        if p.is_file()
        and p.suffix.lower() in _IMAGE_SUFFIXES
        and ".venv" not in p.parts
        and "__pycache__" not in p.parts
        and "skins" not in p.parts
        and "whale_girl" not in p.parts
        and "third_party" not in p.parts
        and "build" not in p.parts  # gitignore 构建产物（c-ui-kit 预览截图），不可能入库
    ]
    assert not offenders, f"菜单图标绘制落盘了图片素材：{offenders}"


# --------------------------------------------------------------------------- #
# 3. 托盘接线：命令有图标 / 开关保留勾选 / 退出染红
# --------------------------------------------------------------------------- #
def test_tray_command_and_submenu_rows_have_icons(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    for attr in (
        "_action_restore", "_action_minimize", "_action_bubble_text",
        "_action_data", "_action_update_check", "_action_quit",
        "_action_jp_show_now", "_action_jp_vocab", "_action_jp_mastered",
        "_action_jp_log", "_action_jp_stats", "_action_jp_import",
    ):
        action = getattr(tray, attr)
        assert not action.icon().isNull(), f"{attr} 未挂图标"
    for attr in (
        "_jp_menu", "_scale_menu", "_theme_menu", "_skin_menu",
        "_jp_level_menu", "_jp_duration_menu", "_jp_daily_limit_menu",
        "_jp_review_limit_menu",
    ):
        assert not getattr(tray, attr).icon().isNull(), f"{attr} 子菜单父行未挂图标"


def test_tray_checkable_toggles_keep_native_checkmark(qtbot) -> None:
    """可勾选开关**不挂图标**：Qt 带图标会丢勾选标记，状态将不可见。"""

    tray = TrayController(QIcon(), AppConfig())
    for attr in (
        "_action_listen", "_action_bubble", "_action_autostart",
        "_action_update_auto", "_action_reduce_motion", "_action_jp",
    ):
        action = getattr(tray, attr)
        assert action.isCheckable(), f"{attr} 应为可勾选开关"
        assert action.icon().isNull(), f"{attr} 挂图标会吞掉勾选标记"


def test_tray_radio_children_have_no_icon(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    for mapping in (
        tray._scale_actions, tray._theme_actions, tray._skin_actions,
        tray._jp_level_actions, tray._jp_duration_actions,
        tray._jp_daily_limit_actions, tray._jp_review_limit_actions,
    ):
        for action in mapping.values():
            assert action.icon().isNull(), "单选子项应保留原生勾选、不挂图标"


def test_tray_quit_icon_is_destructive_red(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    got = tray._action_quit.icon().pixmap(C.MENU_ICON_PX, C.MENU_ICON_PX).toImage()
    want = icon_factory.menu_icon(
        "quit", C.SEMANTIC_COLORS["destructive"]
    ).pixmap(C.MENU_ICON_PX, C.MENU_ICON_PX).toImage()
    assert _sig(got) == _sig(want), "退出图标未染 destructive 红"


def test_tray_command_icon_uses_secondary_token(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig())
    got = tray._action_restore.icon().pixmap(C.MENU_ICON_PX, C.MENU_ICON_PX).toImage()
    want = icon_factory.menu_icon(
        "pet", C.SEMANTIC_COLORS["text_secondary"]
    ).pixmap(C.MENU_ICON_PX, C.MENU_ICON_PX).toImage()
    assert _sig(got) == _sig(want), "命令图标未用 text_secondary 中性色"


# --------------------------------------------------------------------------- #
# 4. 行高统一（勾选行 vs 图标行）
# --------------------------------------------------------------------------- #
def test_menu_row_heights_are_uniform(qtbot) -> None:
    tray = TrayController(QIcon(), AppConfig(listen_enabled=True, autostart=True))
    menu = tray.menu
    qtbot.addWidget(menu)
    menu.popup(QPoint(80, 80))
    qtbot.waitUntil(menu.isVisible)
    # 头部身份区 / 分组小标题是刻意异高的特殊行，不参与「条目行高统一」断言。
    heights = {
        menu.actionGeometry(a).height()
        for a in menu.actions()
        if not a.isSeparator() and a.data() not in ("header", "group")
    }
    assert len(heights) == 1, f"菜单行高参差（勾选行 vs 图标行）：{heights}"
    assert heights == {C.MENU_ROW_H_PX}, f"条目行高应为 MENU_ROW_H_PX：{heights}"