"""ui.menu_shadow —— Win11 风格右键菜单：自绘柔和阴影 + 圆角面板。

Windows 上 QMenu 弹出窗口默认带系统 DWM 方块阴影（Win11 观感过时、四角生硬）。
本模块提供 :class:`ShadowMenu` 替代裸 ``QMenu``：

1. ``FramelessWindowHint`` 让弹出窗口成为分层窗口（WS_EX_LAYERED），否则
   ``WA_TranslucentBackground`` 在 Windows 上渲染成不透明黑边（探针实测）；
2. ``NoDropShadowWindowHint`` 关掉 DWM 原生阴影；
3. 窗口四周预留 ``MENU_SHADOW_BAND_PX`` 留白（经 QSS ``padding`` 撑开），
   ``paintEvent`` 在留白区画预模糊的柔和阴影，再画白色圆角面板 + 1px 描边，
   最后交回原生样式画菜单条目（勾选标记 / 子菜单箭头仍由原生绘制）；
4. ``showEvent`` 把窗口整体回移一个留白，使**面板**（而非透明窗口）对齐
   popup 的目标点——否则菜单看起来向右下偏了留白那么大。

阴影位图按面板尺寸缓存：菜单尺寸稳定后只模糊一次，无逐帧开销。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsBlurEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QMenu,
)

from desktop_pet.core import constants as C
from desktop_pet.ui.theme import build_menu_qss

if TYPE_CHECKING:  # pragma: no cover
    from PySide6.QtGui import QPaintEvent, QShowEvent


def _blurred_shadow_pixmap(size: QSize, radius: int, blur_px: int, alpha: int) -> QPixmap:
    """生成柔和阴影位图：黑色圆角矩形 → 高斯模糊。

    位图比 ``size`` 四周各大一圈 ``margin``：圆角矩形画在 margin 内缩区域，
    模糊向外溢出的部分仍落在位图内 —— 否则模糊在位图边界被硬裁，四角
    看起来是直角（面板圆角、阴影切角的「边角打架」观感）。

    Args:
        size: 面板尺寸（阴影形状与之贴合）。
        radius: 面板圆角半径（阴影形状与之贴合）。
        blur_px: 高斯模糊半径（``MENU_SHADOW_BLUR_PX``）。
        alpha: 阴影不透明度 0-255（``MENU_SHADOW_ALPHA``）。

    Returns:
        ``(阴影位图, margin)`` —— 绘制时把位图原点对齐 ``面板左上 - margin``。
    """

    margin = blur_px // 2 + 2
    padded = QSize(size.width() + 2 * margin, size.height() + 2 * margin)
    src = QImage(padded, QImage.Format.Format_ARGB32_Premultiplied)
    src.fill(Qt.GlobalColor.transparent)
    painter = QPainter(src)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(0, 0, 0, alpha))
    painter.drawRoundedRect(
        QRectF(margin, margin, size.width(), size.height()), radius, radius
    )
    painter.end()

    # 高斯模糊没有裸 QPainter API，借 QGraphicsScene 把模糊结果渲染回位图。
    scene = QGraphicsScene()
    scene.setSceneRect(QRectF(0, 0, padded.width(), padded.height()))
    item = QGraphicsPixmapItem(QPixmap.fromImage(src))
    effect = QGraphicsBlurEffect()
    effect.setBlurRadius(blur_px)
    item.setGraphicsEffect(effect)
    scene.addItem(item)

    out = QImage(padded, QImage.Format.Format_ARGB32_Premultiplied)
    out.fill(Qt.GlobalColor.transparent)
    painter2 = QPainter(out)
    scene.render(
        painter2,
        QRectF(0, 0, padded.width(), padded.height()),
        QRectF(0, 0, padded.width(), padded.height()),
    )
    painter2.end()
    return QPixmap.fromImage(out), margin


class ShadowMenu(QMenu):
    """Win11 风格菜单：窗口透明留白 + 自绘柔和阴影 + 白色圆角面板。

    用法与 ``QMenu`` 完全一致（构造参数原样透传），托盘主菜单、各子菜单、
    宠物窗口右键复用菜单均直接替换。
    """

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # 顺序照探针验证的写法：先 FramelessWindowHint，再开半透明，再关 DWM 阴影。
        # （NoDropShadowWindowHint 位会被 Qt 规范化合并——translucent 已隐含关阴影，
        # 但显式保留一次设置作为版本行为差异的兜底。）
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        self.setStyleSheet(build_menu_qss())
        self._shadow: QPixmap | None = None
        self._shadow_size = QSize()
        self._shadow_margin = 0

    # ------------------------------------------------------------------ #
    # 内部实现
    # ------------------------------------------------------------------ #
    def _panel_rect(self) -> QRect:
        """面板矩形：整窗收缩掉四周阴影留白。"""

        band = C.MENU_SHADOW_BAND_PX
        return self.rect().adjusted(band, band, -band, -band)

    # ------------------------------------------------------------------ #
    # 事件
    # ------------------------------------------------------------------ #
    def showEvent(self, event: "QShowEvent") -> None:
        """面板（而非透明窗口）对齐 popup 目标点：整体回移一个留白。"""

        super().showEvent(event)
        band = C.MENU_SHADOW_BAND_PX
        self.move(self.pos() - QPoint(band, band))

    def paintEvent(self, event: "QPaintEvent") -> None:
        """自绘阴影与面板，条目仍交由原生样式（保留勾选标记 / 子菜单箭头）。"""

        panel = self._panel_rect()
        band = C.MENU_SHADOW_BAND_PX
        painter = QPainter(self)
        # 分层窗口自绘必须先清屏（Source 直接写入像素，而不是叠加）。
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), Qt.GlobalColor.transparent)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self._shadow is None or self._shadow_size != panel.size():
            self._shadow, self._shadow_margin = _blurred_shadow_pixmap(
                panel.size(),
                C.RADIUS["md"],
                C.MENU_SHADOW_BLUR_PX,
                C.MENU_SHADOW_ALPHA,
            )
            self._shadow_size = panel.size()
        # 阴影位图比面板四周各大一圈 margin（模糊外溢余量），绘制时回退对齐
        painter.drawPixmap(
            panel.topLeft()
            - QPoint(self._shadow_margin, self._shadow_margin)
            + QPoint(0, C.MENU_SHADOW_OFFSET_Y),
            self._shadow,
        )

        painter.setPen(QColor(C.SEMANTIC_COLORS["border"]))
        painter.setBrush(QColor(C.SEMANTIC_COLORS["surface"]))
        painter.drawRoundedRect(
            QRectF(panel).adjusted(0.5, 0.5, -0.5, -0.5), C.RADIUS["md"], C.RADIUS["md"]
        )
        painter.end()

        super().paintEvent(event)


__all__ = ["ShadowMenu"]
