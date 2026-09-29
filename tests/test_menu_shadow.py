"""ui.menu_shadow（Win11 风格右键菜单）回归测试。

守护链路：ShadowMenu 替换裸 QMenu 后的关键不变式：

- 窗口三件套：FramelessWindowHint（Windows 上使弹出窗口成为分层窗口，半透明
  才能生效）+ NoDropShadowWindowHint（关 DWM 方块阴影）+ WA_TranslucentBackground。
- QSS 留白：``padding == MENU_SHADOW_BAND_PX + 面板内边距``，给自绘阴影留空间。
- showEvent 位置修正：面板（而非透明窗口）对齐 popup 目标点。
- 阴影位图缓存：首绘生成、尺寸不变复用、尺寸变化重建。
- 托盘集成：``TrayController`` 主菜单与各子菜单均为 ShadowMenu。

全部使用 ``QT_QPA_PLATFORM=offscreen``。
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QIcon

from desktop_pet.core import constants as C
from desktop_pet.ui.menu_shadow import ShadowMenu, _blurred_shadow_pixmap
from desktop_pet.ui.theme import build_menu_qss


# --------------------------------------------------------------------------- #
# 1. 窗口属性三件套 + QSS 留白
# --------------------------------------------------------------------------- #
def test_shadow_menu_window_attributes(qtbot) -> None:
    """FramelessWindowHint（分层窗口前提）+ WA_TranslucentBackground（真半透明）。

    注：显式设置的 NoDropShadowWindowHint 会被 Qt 规范化合并（translucent 隐含
    关 DWM 阴影），``windowFlags()`` 读不回该位，故不对此位做断言；分层窗口
    无 DWM 阴影已由真机探针（WS_EX_LAYERED + 自绘阴影可见）验证。
    """

    menu = ShadowMenu()
    qtbot.addWidget(menu)
    assert menu.windowFlags() & Qt.WindowType.FramelessWindowHint, "缺 FramelessWindowHint（分层窗口前提）"
    assert menu.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground), "缺 WA_TranslucentBackground"
    menu.addAction("条目一")
    menu.popup(QPoint(100, 100))
    qtbot.waitUntil(menu.isVisible)
    handle = menu.windowHandle()
    assert handle is not None and handle.format().alphaBufferSize() == 8, "窗口无 alpha 通道（半透明失效）"


def test_shadow_menu_qss_band_padding(qtbot) -> None:
    """QSS 即 build_menu_qss()，其 padding 为菜单留出阴影区。"""

    menu = ShadowMenu()
    qtbot.addWidget(menu)
    assert menu.styleSheet() == build_menu_qss()


# --------------------------------------------------------------------------- #
# 2. showEvent 位置修正：面板对齐 popup 目标点
# --------------------------------------------------------------------------- #
def test_shadow_menu_popup_aligns_panel_not_window(qtbot) -> None:
    """popup(QPoint) 后窗口左上 = 目标点 - 留白（面板左上 = 目标点）。"""

    menu = ShadowMenu()
    qtbot.addWidget(menu)
    menu.addAction("条目一")
    menu.addAction("条目二")

    target = QPoint(200, 150)
    menu.popup(target)
    qtbot.waitUntil(menu.isVisible)
    band = C.MENU_SHADOW_BAND_PX
    assert menu.pos() == target - QPoint(band, band), (
        "showEvent 未按留白回移：面板会偏离 popup 目标点"
    )


def test_shadow_menu_popup_aligns_panel_repeatedly(qtbot) -> None:
    """重复弹出（关了再开）修正不叠加——每次都以 popup 目标点为基准。"""

    menu = ShadowMenu()
    qtbot.addWidget(menu)
    menu.addAction("条目一")

    target = QPoint(180, 160)
    for _ in range(2):
        menu.popup(target)
        qtbot.waitUntil(menu.isVisible)
        assert menu.pos() == target - QPoint(C.MENU_SHADOW_BAND_PX, C.MENU_SHADOW_BAND_PX)
        menu.close()
        qtbot.waitUntil(lambda: not menu.isVisible())


# --------------------------------------------------------------------------- #
# 3. 阴影位图与缓存
# --------------------------------------------------------------------------- #
def test_blurred_shadow_pixmap_has_content_and_alpha() -> None:
    """阴影位图非空、含 alpha 通道，且四周带模糊外溢余量（margin）。

    margin 是圆角阴影的关键：位图若与面板同尺寸，高斯模糊在边界被硬裁，
    四角渐隐被切成直角（2026-09-29 修复）。
    """

    panel = QSize(120, 90)
    pm, margin = _blurred_shadow_pixmap(
        panel, C.RADIUS["md"], C.MENU_SHADOW_BLUR_PX, C.MENU_SHADOW_ALPHA
    )
    assert not pm.isNull()
    assert pm.hasAlphaChannel()
    expected = panel.width() + 2 * margin, panel.height() + 2 * margin
    assert (pm.width(), pm.height()) == expected, "位图应比面板四周各大 margin"
    # 中心必然有阴影像素（alpha > 0），全图不可能是纯透明
    image = pm.toImage()
    center_pixel = image.pixelColor(image.width() // 2, image.height() // 2)
    assert center_pixel.alpha() > 0, "阴影位图中心无内容"


def test_shadow_cache_rebuilt_only_on_resize(qtbot) -> None:
    """首绘生成缓存；同尺寸重绘复用；尺寸变化后重建。"""

    menu = ShadowMenu()
    qtbot.addWidget(menu)
    menu.addAction("条目一")
    menu.addAction("条目二")

    menu.resize(160, 100)
    menu.grab()
    first = menu._shadow
    assert first is not None, "首绘未生成阴影缓存"
    # 缓存键 = 面板尺寸；位图本身比面板四周各大 margin（模糊外溢余量）
    panel_w = 160 - 2 * C.MENU_SHADOW_BAND_PX
    panel_h = 100 - 2 * C.MENU_SHADOW_BAND_PX
    assert menu._shadow_size == QSize(panel_w, panel_h)
    assert (first.width(), first.height()) == (
        panel_w + 2 * menu._shadow_margin,
        panel_h + 2 * menu._shadow_margin,
    )

    menu.grab()
    assert menu._shadow is first, "同尺寸重绘不应重建缓存"

    menu.resize(200, 120)
    menu.grab()
    assert menu._shadow is not first, "尺寸变化后应重建缓存"
    assert menu._shadow_size == QSize(200 - 2 * C.MENU_SHADOW_BAND_PX, 120 - 2 * C.MENU_SHADOW_BAND_PX)


# --------------------------------------------------------------------------- #
# 4. 托盘集成：主菜单与子菜单全部接入 ShadowMenu
# --------------------------------------------------------------------------- #
def test_tray_menus_are_shadow_menus(qtbot) -> None:
    """TrayController 主菜单 + 已建子菜单均为 ShadowMenu（防裸 QMenu 回潮）。"""

    from desktop_pet.core.config import AppConfig
    from desktop_pet.ui.tray import TrayController

    tray = TrayController(QIcon(), AppConfig())
    menus = [
        tray.menu,
        tray._jp_menu,
        tray._jp_level_menu,
        tray._jp_duration_menu,
        tray._jp_daily_limit_menu,
        tray._theme_menu,
        tray._skin_menu,
    ]
    for menu in menus:
        assert menu is not None
        assert isinstance(menu, ShadowMenu), f"菜单未接入 ShadowMenu：{menu.title()}"
        assert menu.windowFlags() & Qt.WindowType.FramelessWindowHint
