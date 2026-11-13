"""ui.menu_rows —— 右键菜单富条目（QWidgetAction 承载的自绘行 / 头部 / 分组标题）。

预览工件 ``menu-redesign.canvas.tsx`` 的「重设计」形态在 Qt 侧的落地层：语义图标、
迷你开关、行内当前值、分组小标题、头部身份区 + 今日进度、徽标与危险态。

**平台边界**：这些 widget 只在 Qt 自绘菜单（:class:`ui.menu_shadow.ShadowMenu`，
即宠物窗口右键 / Windows 托盘）里渲染；macOS 托盘走系统原生 NSMenu，忽略 widget、
改读 QAction 的 text / icon / check 状态——故每个富条目仍是一个携带完整语义的
QAction（开关保持 checkable 且**不 setIcon**，原生勾选不丢）。

**状态实时性**：行内值 / 徽标 / 进度 / 点缀色一律经 provider 回调在 ``paintEvent``
时读取，配置变化无需逐 widget 同步；只需菜单 ``update()`` 触发重绘
（ShadowMenu.paintEvent 会向子 widget 传播）。

**鼠标 / 键盘**：行 widget 设 ``WA_TransparentForMouseEvents``，事件交回 QMenu，
保留原生键盘导航与悬停高亮（高亮仍由 ShadowMenu 自绘圆角矩形垫在 widget 之下）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget, QWidgetAction

from desktop_pet.core import constants as C
from desktop_pet.ui.icon_factory import menu_icon_pixmap

if TYPE_CHECKING:  # pragma: no cover
    from PySide6.QtGui import QPaintEvent

#: 行内容左右内边距（相对 widget _rect_）：面板内缩 + 行内 padding，再扣除 QMenu
#: 内容区已有的面板内边距（SPACING["xs"]），使图标落点与预览一致。
_PAD = C.MENU_ITEM_INSET_PX + C.SPACING["sm"] - C.SPACING["xs"]
_GAP = C.SPACING["sm"]

#: 行内当前值 / 徽标 / 状态等次级文字字号（px）。
_VAL_FONT_PX = 10
#: 分组小标题字号（px）。
_GROUP_FONT_PX = 10


def _font(px: float, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    f = QFont()
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(weight)
    return f


def _stops_gradient(stops: tuple, rect: QRectF) -> QLinearGradient:
    g = QLinearGradient(rect.topLeft(), rect.bottomRight())
    for pos, color in stops:
        g.setColorAt(float(pos), QColor(color))
    return g


class MenuRowWidget(QWidget):
    """一条富菜单行：图标 + 文本 +（行内值 / swatch / 徽标）+（开关 / ✓ / chevron）。"""

    def __init__(
        self,
        action: QWidgetAction,
        *,
        icon: str | None = None,
        kind: str = "command",
        min_width: int = 0,
        value: Callable[[], str] | None = None,
        swatch: Callable[[], tuple] | None = None,
        badge: Callable[[], str | None] | None = None,
        accent: Callable[[], str] | None = None,
        danger: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._action = action
        self._icon = icon
        self._kind = kind
        self._min_width = min_width
        self._value = value
        self._swatch = swatch
        self._badge = badge
        self._accent = accent
        self._danger = danger

    # -- 几何 -- #
    def _ctrl_width(self) -> int:
        if self._kind == "toggle":
            return C.MENU_SWITCH_W_PX
        if self._kind in ("submenu", "radio"):
            return C.MENU_ICON_PX
        return 0

    def sizeHint(self) -> QSize:  # noqa: N802
        fm = QFontMetrics(_font(C.MENU_FONT_PX))
        w = _PAD * 2 + C.MENU_ICON_PX + _GAP
        w += fm.horizontalAdvance(self._action.text()) + _GAP
        if self._value is not None:
            w += QFontMetrics(_font(_VAL_FONT_PX)).horizontalAdvance(self._value()) + _GAP
        if self._swatch is not None:
            w += 12 + _GAP
        if self._badge is not None and self._badge():
            w += 24 + _GAP
        w += self._ctrl_width()
        return QSize(max(self._min_width, w), C.MENU_ROW_H_PX)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    # -- 绘制 -- #
    def paintEvent(self, event: "QPaintEvent") -> None:  # noqa: N802
        r = QRectF(self.rect())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        act = self._action
        enabled = act.isEnabled()
        checked = act.isChecked()
        c = C.SEMANTIC_COLORS
        accent = self._accent() if self._accent else c["primary"]
        ink = c["destructive"] if self._danger else c["text_primary"]
        if not enabled:
            ink = c["text_faint"]
        ico_color = c["destructive"] if self._danger else c["text_secondary"]
        if not enabled:
            ico_color = c["text_faint"]

        x = r.left() + _PAD
        cy = r.center().y()
        if self._icon:
            pm = menu_icon_pixmap(
                self._icon, ico_color, C.MENU_ICON_PX, self.devicePixelRatioF()
            )
            p.drawPixmap(int(x), int(cy - C.MENU_ICON_PX / 2), pm)
        x += C.MENU_ICON_PX + _GAP

        # 右侧控件预留
        ctrl_w = self._ctrl_width()
        right_edge = r.right() - _PAD
        # 行内值 / swatch / 徽标（右对齐于控件左侧）
        val_text = self._value() if self._value else ""
        badge_text = self._badge() if self._badge else None
        vx = right_edge - ctrl_w - (_GAP if ctrl_w else 0)
        if val_text:
            vf = _font(_VAL_FONT_PX)
            vw = QFontMetrics(vf).horizontalAdvance(val_text)
            vx -= vw
            p.setFont(vf)
            p.setPen(QColor(c["text_faint"] if enabled else c["text_faint"]))
            p.drawText(QRectF(vx, r.top(), vw, r.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, val_text)
            vx -= _GAP
        if self._swatch is not None:
            stops = self._swatch()
            if stops:
                vx -= 12
                sr = QRectF(vx, cy - 6, 12, 12)
                p.setPen(QPen(QColor(c["border"]), 1))
                p.setBrush(_stops_gradient(stops, sr))
                p.drawRoundedRect(sr, 4, 4)
                vx -= _GAP
        if badge_text == "dot":
            vx -= 7
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(accent))
            p.drawEllipse(QRectF(vx, cy - 3.5, 7, 7))
            vx -= _GAP
        elif badge_text:
            bf = _font(_VAL_FONT_PX, QFont.Weight.DemiBold)
            bw = QFontMetrics(bf).horizontalAdvance(badge_text) + 12
            vx -= bw
            br = QRectF(vx, cy - 8, bw, 16)
            p.setPen(QPen(QColor(c["border"]), 1))
            p.setBrush(QColor(c["surface_alt"]))
            p.drawRoundedRect(br, 8, 8)
            p.setFont(bf)
            p.setPen(QColor(c["text_secondary"]))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, badge_text)

        # 文本（占剩余空间，超长省略）
        label_right = vx - _GAP if (val_text or badge_text or self._swatch) else right_edge - ctrl_w - (_GAP if ctrl_w else 0)
        lf = _font(C.MENU_FONT_PX, QFont.Weight.Medium)
        p.setFont(lf)
        p.setPen(QColor(ink))
        lr = QRectF(x, r.top(), max(0.0, label_right - x), r.height())
        elided = QFontMetrics(lf).elidedText(act.text(), Qt.TextElideMode.ElideRight, int(lr.width()))
        p.drawText(lr, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, elided)

        # 右侧控件
        cx = right_edge - ctrl_w
        if self._kind == "toggle":
            sw = QRectF(cx, cy - C.MENU_SWITCH_H_PX / 2, C.MENU_SWITCH_W_PX, C.MENU_SWITCH_H_PX)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(accent if (checked and enabled) else c["border"]))
            p.drawRoundedRect(sw, C.MENU_SWITCH_H_PX / 2, C.MENU_SWITCH_H_PX / 2)
            knob = 12.0
            kx = sw.left() + 2 + (C.MENU_SWITCH_W_PX - knob - 4 if checked else 0)
            p.setBrush(QColor(c["surface"]))
            p.drawEllipse(QRectF(kx, sw.top() + 2, knob, knob))
        elif self._kind == "radio":
            if checked:
                pm = menu_icon_pixmap(
                    "check", accent if enabled else c["text_faint"], 13,
                    self.devicePixelRatioF(),
                )
                p.drawPixmap(int(cx + (C.MENU_ICON_PX - 13) / 2), int(cy - 6.5), pm)
        elif self._kind == "submenu":
            pen = QPen(QColor(c["text_faint"] if enabled else c["text_faint"]))
            pen.setWidthF(1.6)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            p.setPen(pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            path = QPainterPath()
            path.moveTo(cx + 4, cy - 4)
            path.lineTo(cx + 8, cy)
            path.lineTo(cx + 4, cy + 4)
            p.drawPath(path)
        p.end()


class MenuHeaderWidget(QWidget):
    """头部身份区：渐变猫头像 + 名称 + 版本 + 状态行 + 今日进度条。"""

    def __init__(
        self,
        action: QWidgetAction,
        *,
        name: str,
        version: str,
        status: Callable[[], tuple[bool, str]],
        progress: Callable[[], float],
        stops: Callable[[], tuple],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._action = action
        self._name = name
        self._version = version
        self._status = status
        self._progress = progress
        self._stops = stops

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(C.MENU_WIDTH_PX, C.MENU_HEADER_H_PX + 7)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event: "QPaintEvent") -> None:  # noqa: N802
        r = QRectF(self.rect())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = C.SEMANTIC_COLORS
        stops = self._stops()
        av = QRectF(r.left() + 12, r.top() + 8, 36, 36)
        self._draw_cat(p, av, stops)
        tx = av.right() + 10
        p.setFont(_font(13, QFont.Weight.Bold))
        p.setPen(QColor(c["text_primary"]))
        p.drawText(QRectF(tx, r.top() + 8, 120, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._name)
        nw = QFontMetrics(_font(13, QFont.Weight.Bold)).horizontalAdvance(self._name)
        vf = _font(9)
        vw = QFontMetrics(vf).horizontalAdvance(self._version) + 10
        vr = QRectF(tx + nw + 8, r.top() + 10, vw, 14)
        p.setPen(QPen(QColor(c["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(vr, 7, 7)
        p.setFont(vf)
        p.setPen(QColor(c["text_faint"]))
        p.drawText(vr, Qt.AlignmentFlag.AlignCenter, self._version)
        on, status_text = self._status()
        sy = r.top() + 30
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["success"] if on else c["text_faint"]))
        p.drawEllipse(QRectF(tx, sy + 4, 6, 6))
        p.setFont(_font(_VAL_FONT_PX))
        p.setPen(QColor(c["text_secondary"]))
        p.drawText(QRectF(tx + 11, sy, r.right() - tx - 20, 14),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, status_text)
        # 今日进度条
        pr = QRectF(r.left() + 12, r.bottom() - 6, r.width() - 24, 3)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(c["surface_alt"]))
        p.drawRoundedRect(pr, 1.5, 1.5)
        pct = max(0.0, min(1.0, self._progress()))
        if pct > 0:
            fill = QRectF(pr.left(), pr.top(), pr.width() * pct, pr.height())
            p.setBrush(_stops_gradient(stops, fill))
            p.drawRoundedRect(fill, 1.5, 1.5)
        p.end()

    @staticmethod
    def _draw_cat(p: QPainter, rect: QRectF, stops: tuple) -> None:
        grad = _stops_gradient(stops, rect)
        ink = QColor(C.SEMANTIC_COLORS["text_primary"])
        pen = QPen(ink, 2.0)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        p.setPen(pen)
        p.setBrush(grad)
        s = rect.width() / 48.0
        def pt(x: float, y: float) -> tuple[float, float]:
            return rect.left() + x * s, rect.top() + y * s
        ear_l = QPainterPath()
        ear_l.moveTo(*pt(10.5, 15)); ear_l.lineTo(*pt(13.5, 4.5)); ear_l.lineTo(*pt(21, 11.5)); ear_l.closeSubpath()
        ear_r = QPainterPath()
        ear_r.moveTo(*pt(37.5, 15)); ear_r.lineTo(*pt(34.5, 4.5)); ear_r.lineTo(*pt(27, 11.5)); ear_r.closeSubpath()
        p.drawPath(ear_l); p.drawPath(ear_r)
        p.drawEllipse(QRectF(rect.left() + 7.5 * s, rect.top() + 10.5 * s, 33 * s, 33 * s))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(ink)
        p.drawEllipse(QRectF(rect.left() + 16 * s, rect.top() + 22.8 * s, 4 * s, 5.4 * s))
        p.drawEllipse(QRectF(rect.left() + 28 * s, rect.top() + 22.8 * s, 4 * s, 5.4 * s))
        mouth = QPainterPath()
        mouth.moveTo(*pt(20.5, 31))
        mouth.quadTo(*pt(22.25, 32.8), *pt(24, 31))
        mouth.quadTo(*pt(25.75, 32.8), *pt(27.5, 31))
        mp = QPen(ink, 1.5)
        mp.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(mp)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(mouth)


class MenuGroupLabelWidget(QWidget):
    """分组小标题行（互动 / 学习 / 外观 / 偏好）。"""

    def __init__(self, action: QWidgetAction, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self._action = action
        self._text = text

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(C.MENU_WIDTH_PX, C.MENU_GROUP_LABEL_H_PX)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return self.sizeHint()

    def paintEvent(self, event: "QPaintEvent") -> None:  # noqa: N802
        r = QRectF(self.rect())
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(_font(_GROUP_FONT_PX, QFont.Weight.DemiBold))
        p.setPen(QColor(C.SEMANTIC_COLORS["text_faint"]))
        p.drawText(QRectF(r.left() + 16, r.top(), r.width() - 32, r.height()),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, self._text)
        p.end()


def make_row_action(
    menu: QWidget,
    text: str,
    *,
    icon: str | None = None,
    kind: str = "command",
    min_width: int = 0,
    value: Callable[[], str] | None = None,
    swatch: Callable[[], tuple] | None = None,
    badge: Callable[[], str | None] | None = None,
    accent: Callable[[], str] | None = None,
    danger: bool = False,
) -> QWidgetAction:
    """建一个携带富行 widget 的 QWidgetAction（语义仍落在 QAction 上供原生托盘）。"""

    act = QWidgetAction(menu)
    act.setText(text)
    widget = MenuRowWidget(
        act, icon=icon, kind=kind, min_width=min_width, value=value,
        swatch=swatch, badge=badge, accent=accent, danger=danger,
    )
    act.setDefaultWidget(widget)
    menu.addAction(act)
    return act


__all__ = [
    "MenuRowWidget",
    "MenuHeaderWidget",
    "MenuGroupLabelWidget",
    "make_row_action",
]