"""ui.pet_renderer —— QPainter **纯矢量**猫咪渲染器（零外部图片素材）。

绘制层次严格遵循 PRD §4.1：透明底板 → 尾巴 → 身体/后腿 → 头部/耳朵 →
迷你键盘 → 双手（前臂/手掌/手指）→ 面部（眼睛/嘴/腮红）→ 光晕 / ZZZ / 泪点。

缩放由 ``painter.scale(scale, scale)`` 统一施加，几何在**逻辑画布 160×180**内绘制。
配色全部取自 :mod:`desktop_pet.core.constants` 的 ``COLORS``。

.. note::
   绘制几何为渲染层内部细节（非业务阈值），集中定义于本模块顶部的 ``_GEO_*``
   具名常量，避免散落裸数字。
"""

from __future__ import annotations

import math
from typing import Final

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt
from PySide6.QtGui import (
    QBrush,
    QColor,
    QIcon,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)

from desktop_pet.core import constants as C
from desktop_pet.core.pet_model import PetPose

# --------------------------------------------------------------------------- #
# 几何常量（逻辑画布 160×180）
# --------------------------------------------------------------------------- #
_GEO_CANVAS_W: Final[float] = float(C.BASE_W)
_GEO_CANVAS_H: Final[float] = float(C.BASE_H)

# 身体（整体较旧版上移 6px，为底部键盘腾出空间；各部件保持相对关系）
_GEO_BODY_CX: Final[float] = 80.0
_GEO_BODY_CY: Final[float] = 118.0
_GEO_BODY_RX: Final[float] = 45.0
_GEO_BODY_RY: Final[float] = 42.0
_GEO_LEG_RX: Final[float] = 16.0
_GEO_LEG_RY: Final[float] = 11.0

# 头（局部坐标以头中心为原点）
_GEO_HEAD_CX: Final[float] = 80.0
_GEO_HEAD_CY: Final[float] = 68.0
_GEO_HEAD_RX: Final[float] = 40.0
_GEO_HEAD_RY: Final[float] = 36.0
_GEO_EYE_DX: Final[float] = 15.0
_GEO_EYE_DY: Final[float] = -2.0
_GEO_EYE_R: Final[float] = 7.0
_GEO_NOSE_DY: Final[float] = 12.0
_GEO_MOUTH_DY: Final[float] = 21.0
_GEO_BLUSH_DX: Final[float] = 26.0
_GEO_BLUSH_DY: Final[float] = 14.0
_GEO_BLUSH_RX: Final[float] = 9.0
_GEO_BLUSH_RY: Final[float] = 6.0

# 耳朵（局部坐标）
_GEO_EAR_X: Final[float] = 21.0
_GEO_EAR_BASE_Y: Final[float] = -28.0
_GEO_EAR_TIP_Y: Final[float] = -62.0
_GEO_EAR_HALF_W: Final[float] = 15.0

# 迷你键盘（画布底部，敲击落点；纯矢量，见 _draw_keyboard）
_GEO_KEYBOARD_CX: Final[float] = 80.0
_GEO_KEYBOARD_W: Final[float] = 72.0
_GEO_KEYBOARD_H: Final[float] = 16.0
_GEO_KEYBOARD_Y: Final[float] = 160.0        # 底座上沿
_GEO_KEYBOARD_RADIUS: Final[float] = 3.0
_GEO_KEY_COLS: Final[int] = 8                # 每排键数
_GEO_KEY_ROWS: Final[int] = 2                # 键帽排数
_GEO_KEY_W: Final[float] = 6.0
_GEO_KEY_H: Final[float] = 4.0
_GEO_KEY_GAP: Final[float] = 2.0             # 同排相邻键间距
_GEO_KEY_ROW_GAP: Final[float] = 1.5         # 排间距
_GEO_KEY_X0: Final[float] = 49.0             # 首键左沿
_GEO_KEY_ROW0_Y: Final[float] = 162.0        # 首排键帽上沿
_GEO_KEY_SINK_PX: Final[float] = 3.2         # 键帽被按下时的下沉像素（目标 ≥3）
_GEO_KEY_RADIUS: Final[float] = 1.2

# 手（前臂 + 手掌 + 三指；左手在键盘左 1/3、右手在右 1/3）
# 尺寸按 **scale=1.0 实际观感** 标定（用户看到的就是 1x），不靠放大预览撑场面。
_GEO_HAND_L_X: Final[float] = 56.0
_GEO_HAND_R_X: Final[float] = 104.0
_GEO_HAND_SHOULDER_Y: Final[float] = 122.0   # 前臂与身体衔接处
_GEO_HAND_Y: Final[float] = 148.0            # 手掌中心（静止）
_GEO_HAND_PALM_W: Final[float] = 20.0
_GEO_HAND_PALM_H: Final[float] = 14.0
_GEO_HAND_PALM_RADIUS: Final[float] = 5.5
_GEO_FOREARM_W: Final[float] = 10.0          # 前臂粗细
_GEO_FINGER_W: Final[float] = 6.0
_GEO_FINGER_LEN: Final[float] = 10.0         # 手指基础长度（朝下）
_GEO_FINGER_DX: Final[float] = 6.0           # 相邻手指中心间距
_GEO_FINGER_RADIUS: Final[float] = 2.6
_GEO_FINGER_CURL_SHRINK: Final[float] = 0.50  # 弯曲时缩短比例
_GEO_FINGER_LIFT_STRETCH: Final[float] = 0.15  # 抬腕时手指微伸比例
_GEO_HAND_LIFT_PX: Final[float] = 13.5       # 抬腕上移像素（目标 ≥12）
_GEO_HAND_PRESS_PX: Final[float] = 9.0       # 落指下压像素（目标 ≥8）
_GEO_DANGLE_DEG: Final[float] = 38.0         # 被拎起时手臂外摆角度

# 尾巴
_GEO_TAIL_X: Final[float] = 110.0
_GEO_TAIL_Y: Final[float] = 130.0
_GEO_TAIL_LEN: Final[float] = 38.0

# 描边
_STROKE_W: Final[float] = 2.6
_STROKE_W_THIN: Final[float] = 2.0

#: 反锯齿 / 描边导致的额外外扩（逻辑像素），保证收窄脏区不会裁掉边缘像素。
_BOUNDS_PAD_PX: Final[float] = 2.0


class PetRenderer:
    """把 :class:`~desktop_pet.core.pet_model.PetPose` 参数渲染为矢量猫咪。"""

    #: 光晕绘制阈值：``pose.glow_alpha`` 大于该值时，渲染器会绘制**铺满整窗**的
    #: 径向光晕（睡觉的淡蓝柔光 / 兴奋的暖黄光晕），此时脏区无法收窄 —— 详见
    #: :meth:`body_bounds` 与 :meth:`desktop_pet.ui.pet_window.PetWindow.pet_rect`。
    GLOW_ALPHA_EPSILON: Final[float] = 0.01

    def __init__(self) -> None:
        """预构造复用画刷/画笔，避免每帧创建大量临时对象（性能约束 §6）。"""

        self._outline = QPen(QColor(C.COLORS["warm_brown"]))
        self._outline.setWidthF(_STROKE_W)
        self._outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._outline_thin = QPen(QColor(C.COLORS["warm_brown"]))
        self._outline_thin.setWidthF(_STROKE_W_THIN)
        self._outline_thin.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outline_thin.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._brush_cream = QBrush(QColor(C.COLORS["cream"]))
        self._brush_caramel = QBrush(QColor(C.COLORS["caramel"]))
        self._brush_dark = QBrush(QColor(C.COLORS["dark_brown"]))
        self._brush_peach = QBrush(QColor(C.COLORS["peach"]))

        # 前臂：粗圆头描边（暖棕）+ 内填充（奶油白），预先构造避免每帧新建
        self._forearm_outline = QPen(QColor(C.COLORS["warm_brown"]))
        self._forearm_outline.setWidthF(_GEO_FOREARM_W + _STROKE_W)
        self._forearm_outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._forearm_outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._forearm_fill = QPen(QColor(C.COLORS["cream"]))
        self._forearm_fill.setWidthF(_GEO_FOREARM_W)
        self._forearm_fill.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._forearm_fill.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

    # ------------------------------------------------------------------ #
    # 公共入口
    # ------------------------------------------------------------------ #
    def paint(
        self,
        painter: QPainter,
        pose: PetPose,
        scale: float,
        size: QSize,
    ) -> None:
        """在 ``painter`` 上绘制一帧猫咪。

        Args:
            painter: 目标绘制器（调用方已 attach 到窗口）。
            pose: 当前姿态参数。
            scale: 缩放系数（由 ``painter.scale`` 统一施加到逻辑画布）。
            size: 目标绘制区域尺寸（逻辑画布已按 160×180 设计，此参数仅作参考）。
        """

        painter.save()
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
            painter.scale(scale, scale)

            self._draw_glow(painter, pose)
            self._draw_tail(painter, pose)
            self._draw_body(painter, pose)
            self._draw_head(painter, pose)
            self._draw_keyboard(painter, pose)
            self._draw_arms(painter, pose)
            self._draw_face(painter, pose)
            self._draw_zzz(painter, pose)
        finally:
            painter.restore()

    # ------------------------------------------------------------------ #
    # 宠物本体包围盒（FR-35 脏区域局部刷新）
    # ------------------------------------------------------------------ #
    @staticmethod
    def body_bounds(pose: PetPose, scale: float) -> QRect:
        """计算当前姿态下**猫咪本体**的最小包围矩形（窗口像素坐标）。

        用途：``PetWindow`` 据此做脏区域局部刷新（FR-35 / 架构 §6.2），
        避免每帧无意义地整窗重绘。

        .. important::
           本方法**只**覆盖猫身各部件（尾巴 / 身体 / 后腿 / 头 / 耳朵 / 前爪），
           **不含**径向光晕。睡觉（SLEEPING）与兴奋（EXCITED）两态会绘制
           **铺满整窗**的光晕，其 ``pose.glow_alpha > GLOW_ALPHA_EPSILON``；
           调用方必须在这两种状态下回退为**整窗矩形**，否则光晕边缘会被裁掉。
           见 :meth:`desktop_pet.ui.pet_window.PetWindow.pet_rect`。

        Args:
            pose: 当前姿态。
            scale: 缩放档位（0.8 / 1.0 / 1.2）。

        Returns:
            窗口像素坐标下的包围矩形（已钳制在逻辑画布内，保证不裁切本体）。
        """

        x0, y0, x1, y1 = PetRenderer._local_bounds(pose)
        # 映射到窗口像素并向外取整，确保不裁掉边缘像素
        px0 = int(math.floor(x0 * scale))
        py0 = int(math.floor(y0 * scale))
        px1 = int(math.ceil(x1 * scale))
        py1 = int(math.ceil(y1 * scale))
        return QRect(px0, py0, max(1, px1 - px0), max(1, py1 - py0))

    @staticmethod
    def _local_bounds(pose: PetPose) -> tuple[float, float, float, float]:
        """在**逻辑画布坐标**（160×180）内计算猫身包围盒（不含光晕）。

        各部件包围盒的几何与 :meth:`paint` 中的绘制代码一一对应，
        并统一按"旋转矩形的轴对齐包围盒"处理，保证**保守且不裁切**。
        """

        boxes: list[tuple[float, float, float, float]] = []

        def add(bx0: float, by0: float, bx1: float, by1: float) -> None:
            boxes.append((bx0, by0, bx1, by1))

        rotate = PetRenderer._rotate_rect

        # --- 身体 + 后腿（对应 _draw_body）---
        squish = 1.0 - pose.body_squash
        cy = _GEO_BODY_CY + pose.body_y
        ry = _GEO_BODY_RY * max(0.6, squish)
        rx = _GEO_BODY_RX * (1.0 + pose.body_squash * 0.35)
        add(_GEO_BODY_CX - rx, cy - ry, _GEO_BODY_CX + rx, cy + ry)
        leg_y = cy + ry * 0.55
        add(_GEO_BODY_CX - 26.0, leg_y,
            _GEO_BODY_CX - 26.0 + _GEO_LEG_RX * 2.0, leg_y + _GEO_LEG_RY * 2.0)
        add(_GEO_BODY_CX + 26.0 - _GEO_LEG_RX * 2.0, leg_y,
            _GEO_BODY_CX + 26.0, leg_y + _GEO_LEG_RY * 2.0)

        # --- 头部 + 耳朵（对应 _draw_head / _draw_ear）---
        hcx = _GEO_HEAD_CX + pose.look_x * 0.3
        hcy = _GEO_HEAD_CY + pose.head_y + pose.body_y * 0.35
        hx0, hy0, hx1, hy1 = -_GEO_HEAD_RX, -_GEO_HEAD_RY, _GEO_HEAD_RX, _GEO_HEAD_RY
        for side, angle, tilt in (
            (-1.0, pose.ear_l_angle, pose.ear_l_tilt),
            (1.0, pose.ear_r_angle, pose.ear_r_tilt),
        ):
            # 耳朵路径局部包围盒：x∈[-HW, HW]，y∈[TIP-BASE, 0]
            ex0, ey0, ex1, ey1 = rotate(
                -_GEO_EAR_HALF_W, _GEO_EAR_TIP_Y - _GEO_EAR_BASE_Y,
                _GEO_EAR_HALF_W, 0.0, angle + side * tilt,
            )
            ex0 += side * _GEO_EAR_X
            ex1 += side * _GEO_EAR_X
            ey0 += _GEO_EAR_BASE_Y
            ey1 += _GEO_EAR_BASE_Y
            hx0, hy0 = min(hx0, ex0), min(hy0, ey0)
            hx1, hy1 = max(hx1, ex1), max(hy1, ey1)
        hx0, hy0, hx1, hy1 = rotate(hx0, hy0, hx1, hy1, pose.head_tilt)
        add(hcx + hx0, hcy + hy0, hcx + hx1, hcy + hy1)

        # --- 手（对应 _draw_arms / _draw_hand：前臂 + 手掌 + 手指，含抬腕/落指/弯曲）---
        for side, press, lift, curl in (
            (-1.0, pose.arm_l_press, pose.arm_l_lift, pose.finger_l_curl),
            (1.0, pose.arm_r_press, pose.arm_r_lift, pose.finger_r_curl),
        ):
            hcx = _GEO_HAND_L_X if side < 0 else _GEO_HAND_R_X
            palm_cy = (
                _GEO_HAND_Y - lift * _GEO_HAND_LIFT_PX + press * _GEO_HAND_PRESS_PX
            )
            palm_top = palm_cy - _GEO_HAND_PALM_H / 2.0
            finger_len = (
                _GEO_FINGER_LEN
                * (1.0 - _GEO_FINGER_CURL_SHRINK * curl)
                * (1.0 + _GEO_FINGER_LIFT_STRETCH * lift)
            )
            tip_y = palm_top + _GEO_HAND_PALM_H - 1.0 + finger_len
            # 相对肩部的局部包围盒（含肩部圆头半宽 + 描边外扩）
            half_w = max(_GEO_HAND_PALM_W, _GEO_FOREARM_W) / 2.0 + _STROKE_W
            local_top = -_GEO_FOREARM_W / 2.0 - _STROKE_W
            local_bottom = tip_y - _GEO_HAND_SHOULDER_Y + _STROKE_W
            hx0, hy0, hx1, hy1 = rotate(
                -half_w, local_top, half_w, local_bottom,
                side * pose.arm_dangle * _GEO_DANGLE_DEG,
            )
            add(hcx + hx0, _GEO_HAND_SHOULDER_Y + hy0,
                hcx + hx1, _GEO_HAND_SHOULDER_Y + hy1)

        # --- 迷你键盘（对应 _draw_keyboard：底座 + 下沉键帽，键帽始终在底座内）---
        kb_half_w = _GEO_KEYBOARD_W / 2.0 + _STROKE_W
        add(
            _GEO_KEYBOARD_CX - kb_half_w,
            _GEO_KEYBOARD_Y - _STROKE_W,
            _GEO_KEYBOARD_CX + kb_half_w,
            _GEO_KEYBOARD_Y + _GEO_KEYBOARD_H + _STROKE_W,
        )

        # --- 尾巴（对应 _draw_tail，含 13px 描边半宽与尾尖圆）---
        tox = _GEO_TAIL_X + pose.look_x * 0.15
        toy = _GEO_TAIL_Y + pose.body_y
        length = _GEO_TAIL_LEN * (0.85 + 0.35 * pose.tail_curve)
        curve = 34.0 * (0.4 + pose.tail_curve)
        tail_pad = 13.0 / 2.0
        lx0 = 0.0 - tail_pad
        lx1 = max(length * 1.25, length + 12.0) + tail_pad
        ly0 = -curve * 1.2 - tail_pad
        ly1 = 0.0 + tail_pad
        tx0, ty0, tx1, ty1 = rotate(lx0, ly0, lx1, ly1, pose.tail_angle)
        add(tox + tx0, toy + ty0, tox + tx1, toy + ty1)

        # --- 合并 + 反锯齿外扩 + 钳制到逻辑画布 ---
        bx0 = max(0.0, min(b[0] for b in boxes) - _BOUNDS_PAD_PX)
        by0 = max(0.0, min(b[1] for b in boxes) - _BOUNDS_PAD_PX)
        bx1 = min(_GEO_CANVAS_W, max(b[2] for b in boxes) + _BOUNDS_PAD_PX)
        by1 = min(_GEO_CANVAS_H, max(b[3] for b in boxes) + _BOUNDS_PAD_PX)
        return bx0, by0, bx1, by1

    @staticmethod
    def _rotate_rect(
        x0: float, y0: float, x1: float, y1: float, deg: float
    ) -> tuple[float, float, float, float]:
        """把矩形绕原点旋转 ``deg`` 度，返回其**轴对齐包围盒**（保守、不裁切）。"""

        if deg == 0.0:
            return x0, y0, x1, y1
        rad = math.radians(deg)
        cos_a = math.cos(rad)
        sin_a = math.sin(rad)
        xs: list[float] = []
        ys: list[float] = []
        for px, py in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            xs.append(px * cos_a - py * sin_a)
            ys.append(px * sin_a + py * cos_a)
        return min(xs), min(ys), max(xs), max(ys)

    # ------------------------------------------------------------------ #
    # 托盘图标（猫脸剪影，透明背景，PRD §4.4 / FR-25）
    # ------------------------------------------------------------------ #
    @staticmethod
    def build_tray_icon() -> QIcon:
        """用 QPainter 现画猫脸小图标（16/32px），返回 ``QIcon``。"""

        icon = QIcon()
        for px_size in (16, 32):
            pixmap = QPixmap(px_size, px_size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                s = px_size / 32.0
                painter.scale(s, s)
                PetRenderer._paint_tray_face(painter)
            finally:
                painter.end()
            icon.addPixmap(pixmap)
        return icon

    @staticmethod
    def _paint_tray_face(painter: QPainter) -> None:
        """在 32×32 逻辑坐标内绘制猫脸剪影。"""

        outline = QPen(QColor(C.COLORS["warm_brown"]))
        outline.setWidthF(2.0)
        outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        caramel = QBrush(QColor(C.COLORS["caramel"]))
        dark = QBrush(QColor(C.COLORS["dark_brown"]))

        # 耳朵
        painter.setPen(outline)
        painter.setBrush(caramel)
        for cx in (12.0, 22.0):
            ear = QPainterPath()
            ear.moveTo(cx - 5.0, 12.0)
            ear.lineTo(cx, 3.0)
            ear.lineTo(cx + 5.0, 12.0)
            ear.closeSubpath()
            painter.drawPath(ear)

        # 圆脸
        painter.setBrush(caramel)
        painter.drawEllipse(QRectF(6.0, 9.0, 20.0, 18.0))

        # 眼睛
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(dark)
        painter.drawEllipse(QRectF(11.0, 15.0, 3.0, 3.6))
        painter.drawEllipse(QRectF(18.0, 15.0, 3.0, 3.6))
        # 高光
        painter.setBrush(QBrush(QColor(C.COLORS["white"])))
        painter.drawEllipse(QRectF(11.6, 15.4, 1.1, 1.3))
        painter.drawEllipse(QRectF(18.6, 15.4, 1.1, 1.3))

        # 小嘴
        painter.setPen(QPen(QColor(C.COLORS["warm_brown"]), 1.4))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        mouth = QPainterPath()
        mouth.moveTo(15.0, 21.0)
        mouth.lineTo(16.0, 22.5)
        mouth.lineTo(17.5, 21.0)
        painter.drawPath(mouth)

    # ------------------------------------------------------------------ #
    # 各部件绘制
    # ------------------------------------------------------------------ #
    def _draw_glow(self, painter: QPainter, pose: PetPose) -> None:
        """专注/兴奋的暖黄光晕 或 睡觉的淡蓝柔光（PRD §4.2）。"""

        if pose.glow_alpha <= self.GLOW_ALPHA_EPSILON:
            return
        base = QColor(C.COLORS["glow_blue"] if pose.zzz_alpha > 0.05 else C.COLORS["glow_yellow"])
        base.setAlphaF(min(1.0, max(0.0, pose.glow_alpha)) * 0.55)
        trans = QColor(base)
        trans.setAlpha(0)

        cx = _GEO_BODY_CX + pose.look_x * 0.2
        cy = _GEO_BODY_CY + pose.body_y
        radius = _GEO_BODY_RY * 2.1
        gradient = QRadialGradient(QPointF(cx, cy), radius)
        gradient.setColorAt(0.0, base)
        gradient.setColorAt(1.0, trans)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0))

    def _draw_tail(self, painter: QPainter, pose: PetPose) -> None:
        """尾巴：以根部为轴旋转 ``tail_angle``，弯曲程度随 ``tail_curve``。"""

        painter.save()
        try:
            ox = _GEO_TAIL_X + pose.look_x * 0.15
            oy = _GEO_TAIL_Y + pose.body_y
            painter.translate(ox, oy)
            painter.rotate(pose.tail_angle)

            length = _GEO_TAIL_LEN * (0.85 + 0.35 * pose.tail_curve)
            curve = 34.0 * (0.4 + pose.tail_curve)
            path = QPainterPath()
            path.moveTo(0.0, 0.0)
            path.quadTo(length * 0.55, -curve * 0.35, length, -curve * 0.15)
            path.quadTo(length * 1.25, -curve * 0.75, length * 1.15, -curve * 1.15)

            pen = QPen(QColor(C.COLORS["caramel"]))
            pen.setWidthF(13.0)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

            # 描边
            painter.setPen(self._outline)
            painter.drawPath(path)

            # 尾巴尖（浅焦糖已覆盖，加深一点点花纹感）
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._brush_caramel)
            painter.drawEllipse(QRectF(length * 1.0, -curve * 1.2, 12.0, 12.0))
        finally:
            painter.restore()

    def _draw_body(self, painter: QPainter, pose: PetPose) -> None:
        """身体/后腿：呼吸与挤压影响高度。"""

        squish = 1.0 - pose.body_squash
        cy = _GEO_BODY_CY + pose.body_y
        ry = _GEO_BODY_RY * max(0.6, squish)
        rx = _GEO_BODY_RX * (1.0 + pose.body_squash * 0.35)

        # 后腿（先画，位于身体下缘）
        painter.setPen(self._outline)
        painter.setBrush(self._brush_cream)
        leg_y = cy + ry * 0.55
        painter.drawEllipse(QRectF(_GEO_BODY_CX - 26.0, leg_y, _GEO_LEG_RX * 2.0, _GEO_LEG_RY * 2.0))
        painter.drawEllipse(QRectF(_GEO_BODY_CX + 26.0 - _GEO_LEG_RX * 2.0, leg_y,
                                   _GEO_LEG_RX * 2.0, _GEO_LEG_RY * 2.0))

        # 身体
        painter.setBrush(self._brush_cream)
        painter.drawEllipse(QRectF(_GEO_BODY_CX - rx, cy - ry, rx * 2.0, ry * 2.0))

        # 腹部浅色高光
        painter.setPen(Qt.PenStyle.NoPen)
        highlight = QColor(C.COLORS["white"])
        highlight.setAlphaF(0.5)
        painter.setBrush(QBrush(highlight))
        painter.drawEllipse(QRectF(
            _GEO_BODY_CX - rx * 0.5,
            cy - ry * 0.35,
            rx * 1.0,
            ry * 1.1,
        ))

    def _draw_head(self, painter: QPainter, pose: PetPose) -> None:
        """头部 + 耳朵（头部整体随 ``head_tilt`` 旋转）。"""

        painter.save()
        try:
            self._head_transform(painter, pose)

            # 耳朵（在头后）
            painter.setPen(self._outline)
            for side in (-1.0, 1.0):
                angle = pose.ear_l_angle if side < 0 else pose.ear_r_angle
                tilt = pose.ear_l_tilt if side < 0 else pose.ear_r_tilt
                self._draw_ear(painter, side, angle, tilt)

            # 头
            painter.setBrush(self._brush_cream)
            painter.setPen(self._outline)
            painter.drawEllipse(QRectF(
                -_GEO_HEAD_RX, -_GEO_HEAD_RY,
                _GEO_HEAD_RX * 2.0, _GEO_HEAD_RY * 2.0,
            ))

            # 头顶浅焦糖花纹
            painter.setPen(Qt.PenStyle.NoPen)
            patch = QColor(C.COLORS["caramel"])
            patch.setAlphaF(0.55)
            painter.setBrush(QBrush(patch))
            painter.drawEllipse(QRectF(-13.0, -_GEO_HEAD_RY + 3.0, 26.0, 16.0))
        finally:
            painter.restore()

    def _draw_ear(self, painter: QPainter, side: float, angle: float, tilt: float) -> None:
        """绘制单只耳朵（三角 + 内侧浅焦糖）。"""

        painter.save()
        try:
            base_x = side * _GEO_EAR_X
            painter.translate(base_x, _GEO_EAR_BASE_Y)
            painter.rotate(angle + side * tilt)

            outer = QPainterPath()
            outer.moveTo(-_GEO_EAR_HALF_W, 0.0)
            outer.lineTo(0.0, _GEO_EAR_TIP_Y - _GEO_EAR_BASE_Y)
            outer.lineTo(_GEO_EAR_HALF_W, 0.0)
            outer.closeSubpath()

            painter.setBrush(self._brush_cream)
            painter.setPen(self._outline)
            painter.drawPath(outer)

            inner = QPainterPath()
            inner.moveTo(-_GEO_EAR_HALF_W * 0.5, -3.0)
            inner.lineTo(0.0, (_GEO_EAR_TIP_Y - _GEO_EAR_BASE_Y) + 6.0)
            inner.lineTo(_GEO_EAR_HALF_W * 0.5, -3.0)
            inner.closeSubpath()
            painter.setBrush(self._brush_caramel)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPath(inner)
        finally:
            painter.restore()

    def _draw_keyboard(self, painter: QPainter, pose: PetPose) -> None:
        """迷你键盘：底座（圆角矩形）+ 两排键帽。

        * **常驻不隐藏**：任何状态（含睡觉 / 拖拽）都绘制。
        * **键帽下沉**：被敲击一侧的键帽随 ``arm_*_press`` 下沉，形成落点反馈；
          左端键受左手按压、右端键受右手按压（按列位置线性加权），中列受两指共同影响。
        * 配色全部取自 ``C.COLORS``（cream 底座 / caramel 键帽 / warm_brown 描边）。
        """

        left = _GEO_KEYBOARD_CX - _GEO_KEYBOARD_W / 2.0
        base = QRectF(left, _GEO_KEYBOARD_Y, _GEO_KEYBOARD_W, _GEO_KEYBOARD_H)
        painter.setPen(self._outline)
        painter.setBrush(self._brush_cream)
        painter.drawRoundedRect(base, _GEO_KEYBOARD_RADIUS, _GEO_KEYBOARD_RADIUS)

        painter.setPen(self._outline_thin)
        painter.setBrush(self._brush_caramel)
        col_span = max(1, _GEO_KEY_COLS - 1)
        for row in range(_GEO_KEY_ROWS):
            key_y = _GEO_KEY_ROW0_Y + row * (_GEO_KEY_H + _GEO_KEY_ROW_GAP)
            for col in range(_GEO_KEY_COLS):
                key_x = _GEO_KEY_X0 + col * (_GEO_KEY_W + _GEO_KEY_GAP)
                # 越靠左越受左手影响、越靠右越受右手影响
                weight_l = (_GEO_KEY_COLS - 1 - col) / col_span
                weight_r = col / col_span
                sink = (
                    pose.arm_l_press * weight_l + pose.arm_r_press * weight_r
                ) * _GEO_KEY_SINK_PX
                # 键帽**整体刚性下沉**（不压缩高度）：top 与 bottom 位移一致，
                # 保证「键帽下沉量」等于设计值，且键帽不会因压缩而视觉消失。
                rect = QRectF(key_x, key_y + sink, _GEO_KEY_W, _GEO_KEY_H)
                painter.drawRoundedRect(rect, _GEO_KEY_RADIUS, _GEO_KEY_RADIUS)

    def _draw_arms(self, painter: QPainter, pose: PetPose) -> None:
        """双手（前臂 + 手掌 + 三指）：搭在键盘上敲击 / 被拎起时下垂。

        左右手交替由 ``arm_l_*`` / ``arm_r_*`` 通道驱动；``arm_dangle`` 为被拎起
        时的整体外摆旋转。
        """

        for side, hand_x, press, lift, curl in (
            (-1.0, _GEO_HAND_L_X, pose.arm_l_press, pose.arm_l_lift, pose.finger_l_curl),
            (1.0, _GEO_HAND_R_X, pose.arm_r_press, pose.arm_r_lift, pose.finger_r_curl),
        ):
            self._draw_hand(painter, side, hand_x, press, lift, curl, pose.arm_dangle)

    def _draw_hand(
        self,
        painter: QPainter,
        side: float,
        hand_x: float,
        press: float,
        lift: float,
        curl: float,
        dangle: float,
    ) -> None:
        """绘制单手：前臂（肩→腕）+ 手掌 + 三根可弯曲手指。

        Args:
            painter: 目标绘制器。
            side: ``-1`` 左手 / ``+1`` 右手。
            hand_x: 手掌中心横坐标（逻辑画布）。
            press: 落指量 0→1（掌心下移）。
            lift: 抬腕量 0→1（掌心上移、手指微伸）。
            curl: 手指弯曲量 0→1（手指缩短，模拟屈指落键）。
            dangle: 被拎起外摆量 0→1（绕肩点旋转）。
        """

        painter.save()
        try:
            painter.translate(hand_x, _GEO_HAND_SHOULDER_Y)
            painter.rotate(side * dangle * _GEO_DANGLE_DEG)

            palm_cy = (
                _GEO_HAND_Y - lift * _GEO_HAND_LIFT_PX + press * _GEO_HAND_PRESS_PX
            ) - _GEO_HAND_SHOULDER_Y
            palm_top = palm_cy - _GEO_HAND_PALM_H / 2.0
            palm_bottom = palm_cy + _GEO_HAND_PALM_H / 2.0

            # 前臂：暖棕粗描边 + 奶油白内芯（两笔叠画得到描边效果）
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(self._forearm_outline)
            painter.drawLine(QPointF(0.0, 0.0), QPointF(0.0, palm_top))
            painter.setPen(self._forearm_fill)
            painter.drawLine(QPointF(0.0, 0.0), QPointF(0.0, palm_top))

            # 手指（先画，部分被手掌覆盖，露出朝下的指尖）
            finger_len = (
                _GEO_FINGER_LEN
                * (1.0 - _GEO_FINGER_CURL_SHRINK * curl)
                * (1.0 + _GEO_FINGER_LIFT_STRETCH * lift)
            )
            painter.setPen(self._outline_thin)
            painter.setBrush(self._brush_cream)
            for slot in (-1.0, 0.0, 1.0):
                fx = slot * _GEO_FINGER_DX - _GEO_FINGER_W / 2.0
                painter.drawRoundedRect(
                    QRectF(fx, palm_bottom - 1.5, _GEO_FINGER_W, finger_len),
                    _GEO_FINGER_RADIUS,
                    _GEO_FINGER_RADIUS,
                )

            # 手掌（覆盖手指根部）
            painter.setPen(self._outline)
            painter.setBrush(self._brush_cream)
            painter.drawRoundedRect(
                QRectF(
                    -_GEO_HAND_PALM_W / 2.0,
                    palm_top,
                    _GEO_HAND_PALM_W,
                    _GEO_HAND_PALM_H,
                ),
                _GEO_HAND_PALM_RADIUS,
                _GEO_HAND_PALM_RADIUS,
            )

            # 掌垫（蜜桃粉，保留猫爪辨识度；同时作为幅度的可视测量锚点）
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._brush_peach)
            painter.drawEllipse(QRectF(-5.5, palm_top + 6.0, 11.0, 5.5))
        finally:
            painter.restore()

    def _draw_face(self, painter: QPainter, pose: PetPose) -> None:
        """面部：眼睛 / 鼻 / 嘴 / 腮红 / 泪点。"""

        painter.save()
        try:
            self._head_transform(painter, pose)

            # 腮红（在眼睛下方两侧）
            if pose.blush_alpha > 0.01:
                blush = QColor(C.COLORS["peach"])
                blush.setAlphaF(min(1.0, max(0.0, pose.blush_alpha)))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(blush))
                for side in (-1.0, 1.0):
                    painter.drawEllipse(QRectF(
                        side * _GEO_BLUSH_DX - _GEO_BLUSH_RX,
                        _GEO_BLUSH_DY - _GEO_BLUSH_RY,
                        _GEO_BLUSH_RX * 2.0,
                        _GEO_BLUSH_RY * 2.0,
                    ))

            # 眼睛
            for side, openness in ((-1.0, pose.eye_open_l), (1.0, pose.eye_open_r)):
                self._draw_eye(painter, side, openness, pose)

            # 鼻子
            nose = QPainterPath()
            nose.moveTo(0.0, _GEO_NOSE_DY - 2.5)
            nose.lineTo(-4.0, _GEO_NOSE_DY + 2.0)
            nose.lineTo(4.0, _GEO_NOSE_DY + 2.0)
            nose.closeSubpath()
            painter.setPen(self._outline_thin)
            painter.setBrush(self._brush_peach)
            painter.drawPath(nose)

            # 嘴
            self._draw_mouth(painter, pose)

            # 泪点（委屈）
            if pose.tear_alpha > 0.01:
                tear = QColor(C.COLORS["glow_blue"])
                tear.setAlphaF(min(1.0, pose.tear_alpha))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(tear))
                painter.drawEllipse(QRectF(-_GEO_EYE_DX - 3.0, 5.0, 5.0, 6.5))
                painter.drawEllipse(QRectF(_GEO_EYE_DX - 2.0, 5.0, 5.0, 6.5))
        finally:
            painter.restore()

    def _draw_eye(
        self,
        painter: QPainter,
        side: float,
        openness: float,
        pose: PetPose,
    ) -> None:
        """绘制单只眼睛：睁眼（椭圆瞳孔）/ 眯眼（弯月弧线）。"""

        cx = side * _GEO_EYE_DX
        cy = _GEO_EYE_DY
        openness = max(0.0, min(1.4, openness))
        curve = pose.eye_curve

        # 弯月眯眼：眼睑弧线（eye_curve 越大越眯；openness 很小时也画弧）
        if openness < 0.18 or curve > 0.55:
            arc = QPainterPath()
            arc.moveTo(cx - _GEO_EYE_R, cy)
            # curve 正 → 向上笑弧 ⌒；负 → 向下委屈弧
            arc.quadTo(cx, cy - 9.0 * (0.6 + max(0.0, curve)), cx + _GEO_EYE_R, cy)
            painter.setPen(QPen(QColor(C.COLORS["dark_brown"]), _STROKE_W_THIN + 0.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(arc)
            return

        ry = _GEO_EYE_R * openness
        painter.setPen(self._outline_thin)
        painter.setBrush(self._brush_dark)
        painter.drawEllipse(QRectF(cx - _GEO_EYE_R, cy - ry, _GEO_EYE_R * 2.0, ry * 2.0))

        # 高光（pupil_dilate 放大高光）
        hl_r = 1.6 + pose.pupil_dilate * 1.4
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(C.COLORS["white"])))
        painter.drawEllipse(QRectF(
            cx - _GEO_EYE_R * 0.35 + pose.look_x * 0.15,
            cy - ry * 0.45 + pose.look_y * 0.15,
            hl_r * 2.0,
            hl_r * 2.0,
        ))

    def _draw_mouth(self, painter: QPainter, pose: PetPose) -> None:
        """绘制嘴型：笑弧 / 波浪 / 张开○（可含舌头）。"""

        cy = _GEO_MOUTH_DY
        painter.setPen(QPen(QColor(C.COLORS["warm_brown"]), _STROKE_W_THIN))
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if pose.mouth_open > 0.12:
            # 张开嘴（呵欠 / 兴奋 / 惊讶 / 犯困小圆嘴）
            rx = 6.0 + 7.0 * pose.mouth_open
            ry = 5.0 + 10.0 * pose.mouth_open
            painter.setBrush(self._brush_dark)
            painter.drawEllipse(QRectF(-rx, cy - ry * 0.2, rx * 2.0, ry * 2.0 * 0.9))
            if pose.tongue_show > 0.1:
                tongue = QColor(C.COLORS["peach"])
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(tongue))
                painter.drawEllipse(QRectF(
                    -rx * 0.5, cy + ry * 0.1,
                    rx * 1.0, ry * 0.85 * pose.tongue_show,
                ))
            return

        curve = pose.mouth_curve
        if abs(curve) < 0.12:
            # 平坦短线
            painter.drawLine(QPointF(-6.0, cy), QPointF(6.0, cy))
            return

        if curve < 0.0:
            # 波浪委屈嘴
            path = QPainterPath()
            path.moveTo(-9.0, cy)
            path.cubicTo(-4.5, cy + 4.0 * (-curve), -1.5, cy - 4.0 * (-curve), 0.0, cy)
            path.cubicTo(1.5, cy + 4.0 * (-curve), 4.5, cy - 4.0 * (-curve), 9.0, cy)
            painter.drawPath(path)
            return

        # 上扬笑弧
        arc = QPainterPath()
        arc.moveTo(-9.0, cy - 1.5 * curve)
        arc.quadTo(0.0, cy + 6.5 * curve, 9.0, cy - 1.5 * curve)
        painter.drawPath(arc)

    def _draw_zzz(self, painter: QPainter, pose: PetPose) -> None:
        """睡觉头顶的 ZZZ（FR-09 / PRD §4.5）。"""

        if pose.zzz_alpha <= 0.01:
            return
        color = QColor(C.COLORS["warm_brown"])
        color.setAlphaF(min(1.0, max(0.0, pose.zzz_alpha)))
        painter.setPen(QPen(color, 2.4))
        font = painter.font()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        base_x = _GEO_HEAD_CX + _GEO_HEAD_RX * 0.7
        base_y = _GEO_HEAD_CY - _GEO_HEAD_RY * 0.9
        painter.drawText(QPointF(base_x, base_y), "Z")
        painter.drawText(QPointF(base_x + 10.0, base_y - 10.0), "z")
        painter.drawText(QPointF(base_x + 18.0, base_y - 19.0), "z")

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #
    def _head_transform(self, painter: QPainter, pose: PetPose) -> None:
        """把绘制坐标系移动到头部中心并施加倾斜旋转。"""

        painter.translate(
            _GEO_HEAD_CX + pose.look_x * 0.3,
            _GEO_HEAD_CY + pose.head_y + pose.body_y * 0.35,
        )
        painter.rotate(pose.head_tilt)


__all__ = ["PetRenderer"]
