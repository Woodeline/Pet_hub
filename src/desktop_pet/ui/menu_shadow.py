"""ui.menu_shadow —— 扁平紧凑风格右键菜单：极淡阴影 + 小圆角面板。

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

from PySide6.QtCore import QPoint, QRect, QRectF, QSize, Qt, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QGraphicsBlurEffect,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QMenu,
    QWidgetAction,
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
    """扁平紧凑风格菜单：窗口透明留白 + 极淡阴影 + 白色小圆角面板。

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
        #: 入场动效时长（ms）；0 = 直通（reduce_motion）。由 tray 同步。
        self.motion_ms: int = C.MENU_MOTION_MS
        self._anim: QPropertyAnimation | None = None
        #: 富行父行经 QWidgetAction.setMenu 挂载时，addMenu 的 associatedObjects
        #: 链路不成立；由 tray 显式记录视觉上级以保留子菜单贴合几何。
        self._parent_menu_override: QMenu | None = None

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
        """面板（而非透明窗口）对齐 popup 目标点；子菜单与父菜单面板紧贴。

        顶层菜单：整体回移一个留白，使**面板**左上角落在 popup 目标点。
        子菜单：Qt 把子菜单**窗口**贴着父菜单**窗口**边缘放置，而两侧窗口各有
        一圈透明阴影留白 → 面板之间出现约 ``2 × band`` 的空隙（观感松散）。
        此处按父菜单面板边缘重排：左右开合方向沿用 Qt 的判定（以子菜单窗口
        相对父窗口的横向位置区分），垂直仍回移一拍使面板顶与条目顶对齐。
        """

        super().showEvent(event)
        band = C.MENU_SHADOW_BAND_PX
        parent_menu = self._visual_parent_menu()
        if parent_menu is not None:
            self._align_flush_with(parent_menu)
        else:
            self.move(self.pos() - QPoint(band, band))
        self._play_enter_motion()

    def _play_enter_motion(self) -> None:
        """入场淡入（motion_ms）；reduce_motion / 0 时直通不透明。"""

        if self._anim is not None:
            self._anim.stop()
            self._anim = None
        if self.motion_ms <= 0:
            self.setWindowOpacity(1.0)
            return
        self.setWindowOpacity(0.0)
        anim = QPropertyAnimation(self, b"windowOpacity", self)
        anim.setDuration(self.motion_ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)
        self._anim = anim

    def _visual_parent_menu(self) -> QMenu | None:
        """返回本菜单作为子菜单时**所属**的那一级菜单（顶层菜单返回 ``None``）。

        不能用 ``parent()`` / ``parentWidget()``：托盘里的子菜单一律以主菜单为
        构造父级，多级嵌套（「日语学习 → 难度」）时它们指向的是主菜单而非真正
        的上一级；而 action 的关联控件记录的是 ``addMenu`` 挂载到的那个菜单。
        """

        action = self.menuAction()
        if action is not None:
            for obj in action.associatedObjects():
                if isinstance(obj, QMenu) and obj is not self:
                    return obj
        return self._parent_menu_override

    def _align_flush_with(self, parent_menu: QMenu) -> None:
        """把本子菜单面板的侧边贴到父菜单面板边缘（零间隙）。"""

        band = C.MENU_SHADOW_BAND_PX
        parent_topleft = parent_menu.mapToGlobal(QPoint(0, 0))
        parent_panel = parent_menu.rect().adjusted(
            band, band, -band, -band
        ).translated(parent_topleft)
        panel_w = self.width() - 2 * band
        # 子菜单在父窗口右半边展开 → 向右贴；反之（屏幕右缘翻转）向左贴。
        opens_right = self.x() >= parent_topleft.x() + parent_menu.width() // 2
        panel_left = (
            parent_panel.right() + 1 if opens_right else parent_panel.left() - panel_w
        )
        self.move(panel_left - band, self.y() - band)

    def paintEvent(self, event: "QPaintEvent") -> None:
        """自绘阴影、面板与条目高亮，文字仍交由原生样式绘制。"""

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
                C.MENU_PANEL_RADIUS_PX,
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
            QRectF(panel).adjusted(0.5, 0.5, -0.5, -0.5),
            C.MENU_PANEL_RADIUS_PX,
            C.MENU_PANEL_RADIUS_PX,
        )

        self._paint_item_highlight(painter)
        painter.end()

        # 富条目 widget 的状态（勾选 / 行内值 / 徽标 / 进度）在 paint 时实时读取；
        # 菜单重绘时向子 widget 传播一次 update，保证配置变化后无需逐行同步。
        for act in self.actions():
            if isinstance(act, QWidgetAction):
                widget = act.defaultWidget()
                if widget is not None:
                    widget.update()

        super().paintEvent(event)

    def _paint_item_highlight(self, painter: QPainter) -> None:
        """自绘条目悬停/键盘选中高亮（圆角、四周内缩）。

        QSS 的 ``QMenu::item`` 不支持圆角（``border-radius`` 被原生样式忽略，
        高亮呈贴边方角）。这里用圆角矩形自绘，QSS 中 ``::item:selected`` 背景
        置透明，文字/勾选/箭头仍由原生样式绘制在上面。
        """

        active = self.activeAction()
        if active is None or active.isSeparator() or not active.isEnabled():
            return
        rect = QRectF(self.actionGeometry(active))
        if rect.isEmpty():
            return
        # 横向以**面板**为基准内缩 MENU_ITEM_INSET_PX（不随 QSS 内边距漂移，勾选
        # 标记仍落在高亮内）；纵向内缩 1px，相邻条目的高亮之间留一道细缝。
        panel = QRectF(self._panel_rect())
        rect.setLeft(panel.left() + C.MENU_ITEM_INSET_PX)
        rect.setRight(panel.right() - C.MENU_ITEM_INSET_PX)
        rect.adjust(0.0, 1.0, 0.0, -1.0)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C.SEMANTIC_COLORS["surface_alt"]))
        painter.drawRoundedRect(rect, C.MENU_ITEM_RADIUS_PX, C.MENU_ITEM_RADIUS_PX)


__all__ = ["ShadowMenu"]
