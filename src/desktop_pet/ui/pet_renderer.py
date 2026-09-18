"""ui.pet_renderer —— QPainter **纯矢量**团子猫渲染器（零外部图片素材）。

视觉基准（参考图）：一只**圆滚滚的团子猫**，头与身体融合为一个圆球、顶部两只小三角耳、
填充为**柔和全息彩虹**对角渐变、所有轮廓均为**厚实纯黑描边**、脸部极简（两个近黑实心
椭圆眼 + ω 形小弯嘴）。猫**坐在透视键盘后方**，两条短粗前肢搭在键盘上；左下角有一只
深灰鼠标；左侧伸出一条粗弧尾巴。

绘制层次（决定遮挡，"猫坐在键盘后面"的关键）：

    径向光晕（最底） → 尾巴 → 团子主体（含耳朵/后肢） → 透视键盘（盖住身体下沿）
    → 鼠标 → 前肢 + 爪子（盖在键盘之上） → 脸 → ZZZ

缩放由 ``painter.scale(scale, scale)`` 统一施加，几何在**逻辑画布 160×180**内绘制。
配色 / 渐变 / 描边宽度全部取自 :mod:`desktop_pet.core.constants`。

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
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
)

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.pet_model import PetPose

# --------------------------------------------------------------------------- #
# 几何常量（逻辑画布 160×180）
# --------------------------------------------------------------------------- #
_GEO_CANVAS_W: Final[float] = float(C.BASE_W)
_GEO_CANVAS_H: Final[float] = float(C.BASE_H)

# 团子主体（头身融合的圆球）
_GEO_BODY_CX: Final[float] = 80.0
_GEO_BODY_CY: Final[float] = 77.0
_GEO_BODY_RX: Final[float] = 48.0
_GEO_BODY_RY: Final[float] = 45.0

# 耳朵（相对体心的三角耳）
_GEO_EAR_X: Final[float] = 27.0          # 耳根距体心横向偏移
_GEO_EAR_BASE_INSET: Final[float] = 9.0  # 耳根相对身体顶部的下沉（融入轮廓）
_GEO_EAR_LEN: Final[float] = 25.0        # 耳高
_GEO_EAR_HALF_W: Final[float] = 12.5     # 耳根半宽

# 脸（相对体心）
_GEO_EYE_DX: Final[float] = 16.0
_GEO_EYE_DY: Final[float] = -8.0
_GEO_EYE_RX: Final[float] = 6.0
_GEO_EYE_RY: Final[float] = 6.8
_GEO_MOUTH_DY: Final[float] = 9.0
_GEO_BLUSH_DX: Final[float] = 27.0
_GEO_BLUSH_DY: Final[float] = 5.0
_GEO_BLUSH_RX: Final[float] = 9.0
_GEO_BLUSH_RY: Final[float] = 5.5

# 后肢：参考图为「头身融合的单个圆球」，不另绘可分辨的后腿 —— 团子底部自然收束
# 即视觉上的后肢；此处仅保留语义说明，避免多余的侧面凸块破坏圆润剪影。

# 前肢 / 爪子（从团子前下方伸出，短粗，末端圆润爪）
_GEO_HAND_L_X: Final[float] = 62.0
_GEO_HAND_R_X: Final[float] = 99.0
_GEO_HAND_SHOULDER_Y: Final[float] = 118.0  # 前肢与身体衔接处（贴近身体下沿）
_GEO_HAND_Y: Final[float] = 130.0           # 爪子中心（静止，搭在键盘上）
_GEO_PAW_W: Final[float] = 21.0
_GEO_PAW_H: Final[float] = 15.0
_GEO_FOREARM_W: Final[float] = 12.0
_GEO_TOE_DX: Final[float] = 4.6             # 趾凸距爪中心横向偏移
_GEO_TOE_R: Final[float] = 2.9
_GEO_HAND_LIFT_PX: Final[float] = 13.5      # 抬腕上移像素（目标 >=12）
_GEO_HAND_PRESS_PX: Final[float] = 10.0     # 落指下压像素（目标 >=8，留抗锯齿余量）
_GEO_DANGLE_DEG: Final[float] = 38.0        # 被拎起时前肢外摆角度

# 透视键盘（整块斜放的四边形：上下边**同向倾斜** + 键帽同角剪切 + 前缘厚度）
# 局部坐标系以键盘中心为原点、先绘制再整体旋转 `_GEO_KEYBOARD_TILT` 度。
_GEO_KEYBOARD_CX: Final[float] = 84.0
_GEO_KEYBOARD_CY: Final[float] = 140.0        # 局部原点（= 键面中心）
_GEO_KEYBOARD_TILT: Final[float] = -9.0       # 整块键盘的旋转角（度）→ 45° 俯视感
_GEO_KEYBOARD_TOP_Y: Final[float] = -19.0     # 远边（键面顶部）
_GEO_KEYBOARD_BOTTOM_Y: Final[float] = 15.0   # 近边（键面底部）
_GEO_KEYBOARD_TOP_HALF_W: Final[float] = 37.0  # 远边半宽（窄）
_GEO_KEYBOARD_BOTTOM_HALF_W: Final[float] = 47.0  # 近边半宽（宽）
_GEO_KEYBOARD_THICK: Final[float] = 6.0       # 前缘厚度（深色侧面）
_GEO_KEY_ROWS: Final[int] = 3
_GEO_KEY_COLS: Final[int] = 8
_GEO_KEY_SINK_PX: Final[float] = 4.0          # 键帽被按下时的下沉像素（目标 >=3）
_GEO_KEY_RIGHT_BAND: Final[tuple[float, float]] = (118.0, 148.0)  # 右端键 x 区间（供自证）

# 鼠标（左下角，长轴斜置的椭圆仓；与键盘左前缘留出 2~4px 间隙）
_GEO_MOUSE_CX: Final[float] = 18.0
_GEO_MOUSE_CY: Final[float] = 163.0
_GEO_MOUSE_RX: Final[float] = 13.5
_GEO_MOUSE_RY: Final[float] = 11.0
_GEO_MOUSE_TILT: Final[float] = -16.0

# 尾巴 —— 根部落在团子**左中部轮廓内部**（被主体压住），再向左上方扫出一条饱满的弧。
#
# 形状由三件事共同决定（见 `tail_spine` / `_tail_outline`）：
#   1. **角度积分脊线**：出射方向角 `_GEO_TAIL_THETA0` 沿脊线平滑转向 `+SWEEP`，
#      曲率连续、无折点；
#   2. **宽度剖面**：`w(t) = W1 + (W0-W1)*(1-t^P)`，根部饱满、中段保持、末段才收；
#   3. **圆头尾尖**：末端用半圆帽收口（不做平切），避免"香肠断头"感。
#   根部 x 取 52：在所有表情下，**轮廓路径 + 描边**的最左余量约 3.8px（最坏情况
#   是 EXCITED）。这是刻意留的余量——根部再左移或脊线再拉长，尾尖就会被窗口左沿切掉。
#   改这两个参数前，务必先用 ``_opt/tail_probe.py`` 重新扫参，别凭手感挪。
_GEO_TAIL_X: Final[float] = 52.0          # 根部 x（落在身体轮廓内部，被主体遮挡）
_GEO_TAIL_Y: Final[float] = 92.0          # 根部 y
_GEO_TAIL_LEN: Final[float] = 40.0        # 脊线长度（随 tail_curve 略增）
_GEO_TAIL_THETA0: Final[float] = 153.0    # 出射方向角（度，画布坐标 y 向下）
#   153° ≈ 根部椭圆（半径 48/45）在该点的**外法线**方向（左下 27°）——
#   沿法线出射可让尾巴轮廓与身体轮廓大致正交相交，交界处不出现凹口（"皱褶"）。
_GEO_TAIL_SWEEP0: Final[float] = 50.0     # tail_curve=0 时的全程转向量（度，向上扫）
_GEO_TAIL_SWEEP1: Final[float] = 70.0     # tail_curve=1 时的全程转向量（度）
_GEO_TAIL_W0: Final[float] = 17.5         # 根部宽度（饱满）
_GEO_TAIL_W1: Final[float] = 6.2          # 尾尖宽度（仍有厚度，收在圆帽里）
_GEO_TAIL_TAPER_P: Final[float] = 2.2     # 宽度剖面指数（越大 → 越晚收细）
_GEO_TAIL_GRAD_BIAS: Final[float] = 0.17  # 尾尖相对根部在渐变场上的暖向偏移
_GEO_TAIL_SPINE_N: Final[int] = 20        # 脊线采样段数（决定外缘平滑度）
_GEO_TAIL_CAP_SEGMENTS: Final[int] = 8    # 尾尖圆帽分段数

# 描边
_STROKE_W: Final[float] = C.OUTLINE_W         # 主体厚描边
_STROKE_W_THIN: Final[float] = C.OUTLINE_W * 0.62

#: 反锯齿 / 描边导致的额外外扩（逻辑像素），保证收窄脏区不会裁掉边缘像素。
_BOUNDS_PAD_PX: Final[float] = 2.5


#: 逃离位移的边界余量（逻辑像素）。
#: 脊线只是中心线，**轮廓会超出脊线**（尾尖圆帽半径 ``W1/2`` + 描边半宽 + 抗锯齿），
#: 因此约束脊线时必须把这些余量一起算进去，否则尾尖仍会被窗口左沿切掉。
_FLEE_EDGE_MARGIN: Final[float] = _GEO_TAIL_W1 / 2.0 + _STROKE_W / 2.0 + 1.0


def _flee_axis_limits(
    points: list[tuple[float, float]], weights: tuple[float, ...],
) -> tuple[float, float, float, float]:
    """位移的逐轴上限 ``(最多左, 最多右, 最多上, 最多下)``，均为非负值。

    逐轴限幅（而不是整体等比缩放）是刻意的：尾巴本来就贴着窗口左沿，整体缩放会把
    "往左下躲"整个缩没；逐轴只吃掉被挡住的那一维，自由的维度照样让开。
    """

    lo = _FLEE_EDGE_MARGIN
    hi_x = C.BASE_W - _FLEE_EDGE_MARGIN
    hi_y = C.BASE_H - _FLEE_EDGE_MARGIN
    left = right = up = down = float("inf")
    for (px, py), w in zip(points, weights):
        if w <= 1e-9:
            continue
        left = min(left, (px - lo) / w)
        right = min(right, (hi_x - px) / w)
        up = min(up, (py - lo) / w)
        down = min(down, (hi_y - py) / w)
    return (
        max(0.0, left), max(0.0, right), max(0.0, up), max(0.0, down),
    )


def _apply_flee(
    points: list[tuple[float, float]], dx: float, dy: float,
) -> list[tuple[float, float]]:
    """把尾巴的「逃离位移」按沿脊线的权重叠加到脊线上。

    权重由 :func:`motion.ramp_weights` 给出：根部恒为 0（尾巴永远长在身体上），
    越靠尾尖越大 —— 于是整条尾巴"甩身躲开"，而根部交界处保持贴合。
    位移量按 :func:`_flee_axis_limits` 逐轴限幅，保证轮廓不越出画布。
    """

    if abs(dx) <= 1e-6 and abs(dy) <= 1e-6:
        return points
    weights = motion.ramp_weights(len(points), C.TAIL_EVADE_RAMP_P)
    left, right, up, down = _flee_axis_limits(points, weights)
    dx = motion.clamp(dx, -left, right)
    dy = motion.clamp(dy, -up, down)
    return [
        (p[0] + dx * w, p[1] + dy * w) for p, w in zip(points, weights)
    ]


class PetRenderer:
    """把 :class:`~desktop_pet.core.pet_model.PetPose` 参数渲染为矢量团子猫。"""

    #: 光晕绘制阈值：``pose.glow_alpha`` 大于该值时，渲染器会绘制**铺满整窗**的
    #: 径向光晕（睡觉的淡蓝柔光 / 兴奋的暖黄光晕），此时脏区无法收窄 —— 详见
    #: :meth:`body_bounds` 与 :meth:`desktop_pet.ui.pet_window.PetWindow.pet_rect`。
    GLOW_ALPHA_EPSILON: Final[float] = 0.01

    def __init__(self) -> None:
        """预构造复用画笔 / 画刷，避免每帧创建大量临时对象（性能约束 §6）。"""

        ink = QColor(C.COLORS["ink"])

        self._outline = QPen(ink)
        self._outline.setWidthF(_STROKE_W)
        self._outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._outline_thin = QPen(ink)
        self._outline_thin.setWidthF(_STROKE_W_THIN)
        self._outline_thin.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outline_thin.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._mouth_pen = QPen(ink)
        self._mouth_pen.setWidthF(2.2)
        self._mouth_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._mouth_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._brush_ink = QBrush(ink)
        self._brush_white = QBrush(QColor(C.COLORS["white"]))
        self._brush_mouse = QBrush(QColor(C.COLORS["mouse_body"]))

        self._mouse_hi_pen = QPen(QColor(C.COLORS["mouse_hi"]))
        self._mouse_hi_pen.setWidthF(2.0)
        self._mouse_hi_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        # 前肢：墨黑粗描边 + 白芯（两笔叠画得到描边效果）
        self._forearm_outline = QPen(ink)
        self._forearm_outline.setWidthF(_GEO_FOREARM_W + _STROKE_W)
        self._forearm_outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._forearm_outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._forearm_fill = QPen(QColor(C.COLORS["white"]))
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
        """在 ``painter`` 上绘制一帧团子猫。

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
            self._draw_keyboard(painter, pose)
            self._draw_mouse(painter, pose)
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
           本方法**只**覆盖猫身各部件（尾巴 / 团子主体 / 耳朵 / 后肢 / 前爪 /
           透视键盘 / 鼠标），**不含**径向光晕。睡觉（SLEEPING）与兴奋（EXCITED）
           两态会绘制**铺满整窗**的光晕，其 ``pose.glow_alpha > GLOW_ALPHA_EPSILON``；
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

        # --- 团子主体 + 耳朵（对应 _draw_body 的合并轮廓）---
        squish = 1.0 - pose.body_squash
        cy = _GEO_BODY_CY + pose.body_y
        ry = _GEO_BODY_RY * max(0.55, squish)
        rx = _GEO_BODY_RX * (1.0 + pose.body_squash * 0.35)
        hx0 = _GEO_BODY_CX - rx - _GEO_EAR_HALF_W - _STROKE_W
        hx1 = _GEO_BODY_CX + rx + _GEO_EAR_HALF_W + _STROKE_W
        hy0 = cy - ry - _GEO_EAR_LEN - _STROKE_W
        hy1 = cy + ry + _STROKE_W
        add(hx0, hy0, hx1, hy1)

        # --- 前肢 + 爪子（对应 _draw_arms / _draw_paw，含抬腕/落指/弯曲）---
        for side, press, lift, dangle in (
            (-1.0, pose.arm_l_press, pose.arm_l_lift, pose.arm_dangle),
            (1.0, pose.arm_r_press, pose.arm_r_lift, pose.arm_dangle),
        ):
            hcx = _GEO_HAND_L_X if side < 0 else _GEO_HAND_R_X
            paw_cy = (
                _GEO_HAND_Y - lift * _GEO_HAND_LIFT_PX + press * _GEO_HAND_PRESS_PX
            )
            half_w = _GEO_PAW_W / 2.0 + _GEO_TOE_DX * 0.0 + _STROKE_W
            local_top = -_GEO_FOREARM_W / 2.0 - _STROKE_W
            local_bottom = (
                paw_cy - _GEO_HAND_SHOULDER_Y + _GEO_PAW_H / 2.0 + _STROKE_W
            )
            bx0, by0, bx1, by1 = rotate(
                -half_w, local_top, half_w, local_bottom,
                side * dangle * _GEO_DANGLE_DEG,
            )
            add(hcx + bx0, _GEO_HAND_SHOULDER_Y + by0,
                hcx + bx1, _GEO_HAND_SHOULDER_Y + by1)

        # --- 透视键盘（对应 _draw_keyboard：整体旋转的斜四边形 + 前缘厚度）---
        kx0, ky0, kx1, ky1 = rotate(
            -_GEO_KEYBOARD_BOTTOM_HALF_W - _STROKE_W,
            _GEO_KEYBOARD_TOP_Y - _STROKE_W,
            _GEO_KEYBOARD_BOTTOM_HALF_W + _STROKE_W,
            _GEO_KEYBOARD_BOTTOM_Y + _GEO_KEYBOARD_THICK + _STROKE_W
            + _GEO_KEY_SINK_PX,
            _GEO_KEYBOARD_TILT,
        )
        add(_GEO_KEYBOARD_CX + kx0, _GEO_KEYBOARD_CY + ky0,
            _GEO_KEYBOARD_CX + kx1, _GEO_KEYBOARD_CY + ky1)

        # --- 鼠标（对应 _draw_mouse，斜置椭圆仓）---
        mx0, my0, mx1, my1 = rotate(
            -_GEO_MOUSE_RX - _STROKE_W, -_GEO_MOUSE_RY - _STROKE_W,
            _GEO_MOUSE_RX + _STROKE_W, _GEO_MOUSE_RY + _STROKE_W,
            _GEO_MOUSE_TILT,
        )
        add(_GEO_MOUSE_CX + mx0, _GEO_MOUSE_CY + my0,
            _GEO_MOUSE_CX + mx1, _GEO_MOUSE_CY + my1)

        # --- 尾巴（包围盒直接由 _tail_spine 现算，避免手写盒与绘制脱节）---
        # 每个脊线采样点按「最大半宽 + 描边」外扩 → 保守覆盖整条尾巴（含圆帽）。
        tail_pad = _GEO_TAIL_W0 / 2.0 + _STROKE_W
        for tx, ty in PetRenderer.tail_spine(pose):
            add(tx - tail_pad, ty - tail_pad, tx + tail_pad, ty + tail_pad)

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
    # 托盘图标（团子猫脸小图标，透明背景，PRD §4.4 / FR-25）
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
        """在 32×32 逻辑坐标内绘制团子猫脸图标。"""

        ink = QPen(QColor(C.COLORS["ink"]))
        ink.setWidthF(2.2)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        ink.setCapStyle(Qt.PenCapStyle.RoundCap)

        gradient = QLinearGradient(QPointF(4.0, 4.0), QPointF(28.0, 28.0))
        for pos, hexv in C.BODY_GRADIENT_STOPS:
            gradient.setColorAt(pos, QColor(hexv))

        # 耳 + 圆脸合并为一个轮廓
        face = QPainterPath()
        face.addEllipse(QRectF(5.0, 10.0, 22.0, 20.0))
        for cx in (10.0, 22.0):
            ear = QPainterPath()
            ear.moveTo(cx - 5.0, 12.0)
            ear.lineTo(cx, 2.0)
            ear.lineTo(cx + 5.0, 12.0)
            ear.closeSubpath()
            face = face.united(ear)
        painter.setPen(ink)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(face)

        # 眼睛（近黑实心椭圆 + 白高光）
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(QColor(C.COLORS["ink"])))
        painter.drawEllipse(QRectF(11.0, 17.0, 3.2, 3.8))
        painter.drawEllipse(QRectF(17.8, 17.0, 3.2, 3.8))
        painter.setBrush(QBrush(QColor(C.COLORS["white"])))
        painter.drawEllipse(QRectF(11.7, 17.5, 1.2, 1.4))
        painter.drawEllipse(QRectF(18.5, 17.5, 1.2, 1.4))

        # ω 小弯嘴
        painter.setPen(ink)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        mouth = QPainterPath()
        mouth.moveTo(13.5, 23.5)
        mouth.quadTo(14.8, 25.4, 16.0, 23.9)
        mouth.quadTo(17.2, 25.4, 18.5, 23.5)
        painter.drawPath(mouth)

    # ------------------------------------------------------------------ #
    # 渐变 / 轮廓辅助
    # ------------------------------------------------------------------ #
    @staticmethod
    def _body_gradient(x0: float, y0: float, x1: float, y1: float) -> QLinearGradient:
        """构造「左上 → 右下」的柔和全息彩虹对角渐变。"""

        gradient = QLinearGradient(QPointF(x0, y0), QPointF(x1, y1))
        for pos, hexv in C.BODY_GRADIENT_STOPS:
            gradient.setColorAt(pos, QColor(hexv))
        return gradient

    @staticmethod
    def _body_gradient_axis(pose: PetPose) -> tuple[float, float, float, float]:
        """身体渐变轴的两端点 ``(x0, y0, x1, y1)``（画布坐标）。

        :meth:`_draw_body` 与尾巴取色（:meth:`_tail_gradient_field`）**共用**本方法，
        因此尾巴根部颜色与身体在该处的颜色必然一致（交界零色差）。
        """

        squish = 1.0 - pose.body_squash
        cx = _GEO_BODY_CX
        cy = _GEO_BODY_CY + pose.body_y
        ry = _GEO_BODY_RY * max(0.55, squish)
        rx = _GEO_BODY_RX * (1.0 + pose.body_squash * 0.35)
        return cx - rx, cy - ry, cx + rx, cy + ry

    @classmethod
    def _tail_gradient_field(cls, pose: PetPose, x: float, y: float) -> float:
        """身体渐变场在画布点 ``(x, y)`` 处的归一化参数 ``[0, 1]``。

        用于按**位置**取色：尾巴根部直接取该值，即可与身体底色无缝衔接。
        """

        x0, y0, x1, y1 = cls._body_gradient_axis(pose)
        vx, vy = x1 - x0, y1 - y0
        denom = vx * vx + vy * vy or 1.0
        return ((x - x0) * vx + (y - y0) * vy) / denom

    # ------------------------------------------------------------------ #
    # 各部件绘制
    # ------------------------------------------------------------------ #
    def _draw_glow(self, painter: QPainter, pose: PetPose) -> None:
        """专注/兴奋的暖黄光晕 或 睡觉的淡蓝柔光（PRD §4.2）。"""

        if pose.glow_alpha <= self.GLOW_ALPHA_EPSILON:
            return
        base = QColor(
            C.COLORS["glow_blue"] if pose.zzz_alpha > 0.05 else C.COLORS["glow_yellow"]
        )
        base.setAlphaF(min(1.0, max(0.0, pose.glow_alpha)) * 0.55)
        trans = QColor(base)
        trans.setAlpha(0)

        cx = _GEO_BODY_CX + pose.look_x * 0.2
        cy = _GEO_BODY_CY + pose.body_y
        radius = _GEO_BODY_RY * 2.2
        gradient = QRadialGradient(QPointF(cx, cy), radius)
        gradient.setColorAt(0.0, base)
        gradient.setColorAt(1.0, trans)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(gradient))
        painter.drawEllipse(QRectF(cx - radius, cy - radius, radius * 2.0, radius * 2.0))

    # ------------------------------------------------------------------ #
    # 尾巴：几何生成（绘制 / 脏区 / 交互共用同一条脊线）
    # ------------------------------------------------------------------ #
    @staticmethod
    def tail_spine(
        pose: PetPose, *, apply_flee: bool = True,
    ) -> list[tuple[float, float]]:
        """返回尾巴**中心线**在逻辑画布（160×180）下的采样点。

        脊线由「方向角自 ``_GEO_TAIL_THETA0`` 平滑转到 ``+SWEEP``」逐段积分得到
        （曲率连续、无折点），再施加根部位移与 ``pose.tail_angle`` 整体旋转，
        与 :meth:`_draw_tail` 的绘制空间完全一致。

        本方法是尾巴几何的**唯一来源**：

        * :meth:`_draw_tail` 据此生成轮廓；
        * :meth:`_local_bounds` 据此计算脏区包围盒；
        * ``PetWindow`` 据此计算光标与尾巴的亲近度（鼠标交互）。

        Args:
            pose: 当前姿态。
            apply_flee: 是否叠加 ``pose.tail_flee_*``（避让位移）。光标亲近度采样
                必须传 ``False`` —— 否则「位移 → 离光标更远 → 位移变小 → 又靠近」
                会形成自激回路，尾巴在临界距离附近持续抖动。

        Returns:
            ``_GEO_TAIL_SPINE_N + 1`` 个画布坐标点（根 → 尖）。
        """

        curve = motion.clamp(pose.tail_curve, 0.0, 1.0)
        length = _GEO_TAIL_LEN * (0.85 + 0.35 * curve)
        sweep = _GEO_TAIL_SWEEP0 + (_GEO_TAIL_SWEEP1 - _GEO_TAIL_SWEEP0) * curve

        ox = _GEO_TAIL_X + pose.look_x * 0.15
        oy = _GEO_TAIL_Y + pose.body_y
        rot = math.radians(pose.tail_angle)
        cos_r, sin_r = math.cos(rot), math.sin(rot)

        points: list[tuple[float, float]] = []
        local_x = local_y = 0.0
        step = length / _GEO_TAIL_SPINE_N
        for i in range(_GEO_TAIL_SPINE_N + 1):
            points.append(
                (ox + local_x * cos_r - local_y * sin_r,
                 oy + local_x * sin_r + local_y * cos_r)
            )
            angle = math.radians(
                _GEO_TAIL_THETA0
                + sweep * motion.smoothstep(i / _GEO_TAIL_SPINE_N)
            )
            local_x += math.cos(angle) * step
            local_y += math.sin(angle) * step

        return _apply_flee(points, pose.tail_flee_x, pose.tail_flee_y) if apply_flee else points

    @staticmethod
    def _tail_width_at(t: float) -> float:
        """尾巴宽度剖面（``t`` 为沿脊线的归一化位置）。

        ``w(t) = W1 + (W0 - W1) * (1 - t^P)``：根部饱满、中段保持、**末段才收细**。
        原先的线性 taper 会让整条尾巴显得单薄（像一片刀片）。
        """

        return _GEO_TAIL_W1 + (_GEO_TAIL_W0 - _GEO_TAIL_W1) * (
            1.0 - motion.clamp(t, 0.0, 1.0) ** _GEO_TAIL_TAPER_P
        )

    @staticmethod
    def _smooth_closed_path(points: list[tuple[float, float]]) -> QPainterPath:
        """用「过相邻中点的二次贝塞尔」把点列连成**平滑闭合路径**。

        相比逐点 ``lineTo``，粗描边下外缘不会出现多边形棱角。
        """

        path = QPainterPath()
        n = len(points)
        path.moveTo(
            (points[0][0] + points[-1][0]) / 2.0,
            (points[0][1] + points[-1][1]) / 2.0,
        )
        for i in range(n):
            px, py = points[i]
            qx, qy = points[(i + 1) % n]
            path.quadTo(px, py, (px + qx) / 2.0, (py + qy) / 2.0)
        path.closeSubpath()
        return path

    @classmethod
    def _tail_outline(cls, spine: list[tuple[float, float]]) -> QPainterPath:
        """把中心线扩成**平滑闭合轮廓**（左右包络 + 圆头尾尖）。

        尾尖用半圆帽收口而非平切，消除"香肠断头"的僵硬感。
        """

        n = len(spine) - 1
        left: list[tuple[float, float]] = []
        right: list[tuple[float, float]] = []

        for i, (x, y) in enumerate(spine):
            if i == 0:
                dx, dy = spine[1][0] - x, spine[1][1] - y
            elif i == n:
                dx, dy = x - spine[i - 1][0], y - spine[i - 1][1]
            else:
                dx, dy = (
                    spine[i + 1][0] - spine[i - 1][0],
                    spine[i + 1][1] - spine[i - 1][1],
                )
            seg = math.hypot(dx, dy) or 1.0
            nx, ny = -dy / seg, dx / seg
            half = cls._tail_width_at(i / n) / 2.0
            left.append((x + nx * half, y + ny * half))
            right.append((x - nx * half, y - ny * half))

        points = left[:]
        # 圆头尾尖：以末端点为圆心，从左包络半圆扫到右包络
        tip_x, tip_y = spine[-1]
        radius = cls._tail_width_at(1.0) / 2.0
        dx, dy = spine[-1][0] - spine[-2][0], spine[-1][1] - spine[-2][1]
        seg = math.hypot(dx, dy) or 1.0
        base_angle = math.atan2(dy / seg, dx / seg)
        for k in range(1, _GEO_TAIL_CAP_SEGMENTS):
            angle = base_angle - math.pi / 2.0 + math.pi * (k / _GEO_TAIL_CAP_SEGMENTS)
            points.append(
                (tip_x + math.cos(angle) * radius, tip_y + math.sin(angle) * radius)
            )
        points.extend(reversed(right))
        return cls._smooth_closed_path(points)

    def _draw_tail(self, painter: QPainter, pose: PetPose) -> None:
        """尾巴：从团子左中部伸出、向左上扫出的**饱满渐细弧**。

        颜色按身体渐变场取色 —— 根部与身体在该点的颜色**完全相同**（交界无色差），
        沿脊线向暖端偏移 ``_GEO_TAIL_GRAD_BIAS``，形成「越往尾尖越亮暖」的过渡。
        """

        spine = self.tail_spine(pose)
        path = self._tail_outline(spine)

        frac = self._tail_gradient_field(pose, spine[0][0], spine[0][1])
        gradient = QLinearGradient(QPointF(*spine[0]), QPointF(*spine[-1]))
        gradient.setColorAt(
            0.0, QColor(self._sample_gradient(frac - _GEO_TAIL_GRAD_BIAS))
        )
        gradient.setColorAt(1.0, QColor(self._sample_gradient(frac)))

        painter.setPen(self._outline)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(path)

    def _draw_body(self, painter: QPainter, pose: PetPose) -> None:
        """团子主体：头身融合的圆球（含耳朵、后肢），填充柔和全息彩虹渐变。"""

        squish = 1.0 - pose.body_squash
        cx = _GEO_BODY_CX
        cy = _GEO_BODY_CY + pose.body_y
        ry = _GEO_BODY_RY * max(0.55, squish)
        rx = _GEO_BODY_RX * (1.0 + pose.body_squash * 0.35)

        body_rect = QRectF(cx - rx, cy - ry, rx * 2.0, ry * 2.0)
        gradient = self._body_gradient(*self._body_gradient_axis(pose))

        # 轮廓 = 圆球 ∪ 两只三角耳（并集保证"头身融合"、无接缝）
        silhouette = QPainterPath()
        silhouette.addEllipse(body_rect)
        for side in (-1.0, 1.0):
            angle = pose.ear_l_angle if side < 0 else pose.ear_r_angle
            tilt = pose.ear_l_tilt if side < 0 else pose.ear_r_tilt
            silhouette = silhouette.united(
                self._ear_path(side, angle, tilt, cx, cy, rx, ry)
            )

        # 主体轮廓（头身融合为一个圆球，配极简脸）
        painter.setPen(self._outline)
        painter.setBrush(QBrush(gradient))
        painter.drawPath(silhouette)

    def _ear_path(
        self,
        side: float,
        angle: float,
        tilt: float,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
    ) -> QPainterPath:
        """单只三角耳（并入主体轮廓），绕耳根按 ``angle``/``tilt`` 摆动。"""

        base_x = cx + side * _GEO_EAR_X
        base_y = cy - ry + _GEO_EAR_BASE_INSET
        # 对称语义：正角度 → 双耳外张（耷拉）；负角度 → 内收（竖立）
        ang = math.radians(side * angle + side * tilt)
        cos_a, sin_a = math.cos(ang), math.sin(ang)

        def tf(lx: float, ly: float) -> tuple[float, float]:
            return (
                base_x + lx * cos_a - ly * sin_a,
                base_y + lx * sin_a + ly * cos_a,
            )

        p_left = tf(-_GEO_EAR_HALF_W, 0.0)
        p_tip = tf(0.0, -_GEO_EAR_LEN)
        p_right = tf(_GEO_EAR_HALF_W, 0.0)

        path = QPainterPath()
        path.moveTo(p_left[0], p_left[1])
        path.lineTo(p_tip[0], p_tip[1])
        path.lineTo(p_right[0], p_right[1])
        path.closeSubpath()
        return path

    def _draw_keyboard(self, painter: QPainter, pose: PetPose) -> None:
        """透视键盘：**整块斜放**的四边形（上下边同向倾斜 + 键帽同角剪切 + 前缘厚度）。

        做法：把绘制坐标系平移到键盘中心并整体 ``rotate(_GEO_KEYBOARD_TILT)``，
        于是键面的上下边**朝同一方向倾斜**（像一张斜放在桌面上的板子，而非"正梯形"）。
        键帽在"键面空间"里排布，再按同一侧边斜率做横向 warp → 键帽呈**平行四边形**。

        * **常驻不隐藏**：任何状态（含睡觉 / 拖拽）都绘制。
        * **键帽下沉**：被敲击一侧的键帽随 ``arm_*_press`` 下沉（刚性平移），
          左端键受左手按压、右端键受右手按压（按列线性加权）。
        * **厚度**：前缘（近边）向下一段深色侧面 + 一圈黑描边 → 立体板子感。
        """

        top_y = _GEO_KEYBOARD_TOP_Y
        bot_y = _GEO_KEYBOARD_BOTTOM_Y
        top_hw = _GEO_KEYBOARD_TOP_HALF_W
        bot_hw = _GEO_KEYBOARD_BOTTOM_HALF_W
        thick = _GEO_KEYBOARD_THICK

        painter.save()
        try:
            painter.translate(_GEO_KEYBOARD_CX, _GEO_KEYBOARD_CY)
            painter.rotate(_GEO_KEYBOARD_TILT)

            top_face = QPolygonF([
                QPointF(-top_hw, top_y), QPointF(top_hw, top_y),
                QPointF(bot_hw, bot_y), QPointF(-bot_hw, bot_y),
            ])
            front_face = QPolygonF([
                QPointF(-bot_hw, bot_y), QPointF(bot_hw, bot_y),
                QPointF(bot_hw, bot_y + thick), QPointF(-bot_hw, bot_y + thick),
            ])

            # 键面（浅一档的深灰）+ 外圈黑描边
            painter.setPen(self._outline)
            painter.setBrush(self._brush_mouse)
            painter.drawPolygon(top_face)
            painter.drawPolygon(front_face)

            # 前缘厚度（更深的侧面，体现板子厚度）
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._brush_ink)
            painter.drawPolygon(front_face)

            # 键面与前缘的受光高光分界线
            painter.setPen(self._mouse_hi_pen)
            painter.drawLine(QPointF(-bot_hw, bot_y), QPointF(bot_hw, bot_y))

            # 键帽：在"键面空间"排布，再按同一侧边斜率 warp 成平行四边形
            rows = _GEO_KEY_ROWS
            cols = _GEO_KEY_COLS
            col_span = max(1, cols - 1)
            margin = 4.5
            span = max(1.0, 2.0 * top_hw - 2.0 * margin)
            step = span / cols
            painter.setPen(self._outline_thin)
            for row in range(rows):
                fy = (row + 1.0) / (rows + 1.0)
                row_cy = top_y + (bot_y - top_y) * (0.30 + 0.62 * fy)
                key_scale = 0.82 + 0.40 * fy           # 近大远小
                key_w = step * 0.76
                key_h = 5.0 * key_scale
                for col in range(cols):
                    key_cx = -top_hw + margin + step * (col + 0.5)
                    # 越靠左越受左手影响、越靠右越受右手影响
                    weight_l = (cols - 1 - col) / col_span
                    weight_r = col / col_span
                    sink = (
                        pose.arm_l_press * weight_l + pose.arm_r_press * weight_r
                    ) * _GEO_KEY_SINK_PX
                    x0 = key_cx - key_w / 2.0
                    x1 = key_cx + key_w / 2.0
                    y0 = row_cy - key_h / 2.0 + sink
                    y1 = row_cy + key_h / 2.0 + sink
                    poly = QPolygonF([
                        self._kb_warp(x0, y0, top_y, bot_y, top_hw, bot_hw),
                        self._kb_warp(x1, y0, top_y, bot_y, top_hw, bot_hw),
                        self._kb_warp(x1, y1, top_y, bot_y, top_hw, bot_hw),
                        self._kb_warp(x0, y1, top_y, bot_y, top_hw, bot_hw),
                    ])
                    key_color = QColor(self._sample_gradient(col / col_span))
                    painter.setBrush(QBrush(key_color))
                    painter.drawPolygon(poly)
        finally:
            painter.restore()

    @staticmethod
    def _kb_warp(
        x: float, y: float,
        top_y: float, bot_y: float, top_hw: float, bot_hw: float,
    ) -> QPointF:
        """把"键面空间"的点映射到梯形键面：横向按该行的半宽线性放大。

        ``y`` 越靠近近边（``bot_y``），横向放大越多 → 键帽侧边随之倾斜，
        与键面左右边界斜率一致（平行四边形键帽）。
        """

        t = (y - top_y) / max(1e-6, bot_y - top_y)
        half = top_hw + (bot_hw - top_hw) * t
        return QPointF(x * half / top_hw, y)

    @staticmethod
    def _sample_gradient(frac: float) -> str:
        """按 ``frac``（0→1）在彩虹渐变停靠点间取色，用于键帽轮换。"""

        stops = C.BODY_GRADIENT_STOPS
        f = min(1.0, max(0.0, frac))
        for i in range(len(stops) - 1):
            p0, c0 = stops[i]
            p1, c1 = stops[i + 1]
            if f <= p1:
                span = max(1e-6, p1 - p0)
                t = (f - p0) / span
                a, b = QColor(c0), QColor(c1)
                return QColor(
                    int(round(a.red() + (b.red() - a.red()) * t)),
                    int(round(a.green() + (b.green() - a.green()) * t)),
                    int(round(a.blue() + (b.blue() - a.blue()) * t)),
                ).name()
        return stops[-1][1]

    def _draw_mouse(self, painter: QPainter, pose: PetPose) -> None:
        """左下角鼠标：深灰椭圆仓 + 顶部滚轮 + 分割线 + 墨黑描边。"""

        painter.save()
        try:
            painter.translate(_GEO_MOUSE_CX, _GEO_MOUSE_CY)
            painter.rotate(_GEO_MOUSE_TILT)
            rx, ry = _GEO_MOUSE_RX, _GEO_MOUSE_RY

            painter.setPen(self._outline)
            painter.setBrush(self._brush_mouse)
            painter.drawEllipse(QRectF(-rx, -ry, rx * 2.0, ry * 2.0))

            # 顶部滚轮
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor(C.COLORS["mouse_hi"])))
            painter.drawEllipse(QRectF(-1.6, -ry + 2.2, 3.2, 5.0))

            # 分割线
            painter.setPen(self._mouse_hi_pen)
            painter.drawLine(QPointF(-rx + 3.0, -ry * 0.35), QPointF(-1.6, -ry * 0.35))
            painter.drawLine(QPointF(1.6, -ry * 0.35), QPointF(rx - 3.0, -ry * 0.35))
        finally:
            painter.restore()

    def _draw_arms(self, painter: QPainter, pose: PetPose) -> None:
        """两条短粗前肢 + 圆润爪子：搭在键盘上敲击 / 被拎起时外摆下垂。

        左右交替由 ``arm_l_*`` / ``arm_r_*`` 通道驱动；``arm_dangle`` 为被拎起
        时的整体外摆旋转。
        """

        for side, hand_x, press, lift, curl in (
            (-1.0, _GEO_HAND_L_X, pose.arm_l_press, pose.arm_l_lift, pose.finger_l_curl),
            (1.0, _GEO_HAND_R_X, pose.arm_r_press, pose.arm_r_lift, pose.finger_r_curl),
        ):
            self._draw_paw(painter, side, hand_x, press, lift, curl, pose.arm_dangle)

    def _draw_paw(
        self,
        painter: QPainter,
        side: float,
        hand_x: float,
        press: float,
        lift: float,
        curl: float,
        dangle: float,
    ) -> None:
        """绘制单条前肢：前臂（肩→腕）+ 圆润爪 + 2 个小趾凸。

        Args:
            painter: 目标绘制器。
            side: ``-1`` 左 / ``+1`` 右。
            hand_x: 爪子中心横坐标（逻辑画布）。
            press: 落指量 0→1（爪子下移）。
            lift: 抬腕量 0→1（爪子上移）。
            curl: 屈指量 0→1（爪子收紧变扁、趾凸上收，模拟屈指落键）。
            dangle: 被拎起外摆量 0→1（绕肩点旋转）。
        """

        painter.save()
        try:
            painter.translate(hand_x, _GEO_HAND_SHOULDER_Y)
            painter.rotate(side * dangle * _GEO_DANGLE_DEG)

            paw_cy = (
                _GEO_HAND_Y - lift * _GEO_HAND_LIFT_PX + press * _GEO_HAND_PRESS_PX
            ) - _GEO_HAND_SHOULDER_Y
            # 屈指（curl）：爪子**底面与高度固定**（只微收窄宽度 + 上收趾凸），
            # 保证「落指下压」的像素幅度不被屈指通道污染。
            c = max(0.0, min(1.0, curl))
            paw_w = _GEO_PAW_W * (1.0 - 0.12 * c)
            paw_bottom = paw_cy + _GEO_PAW_H / 2.0
            paw_top = paw_cy - _GEO_PAW_H / 2.0

            # 前臂：墨黑粗描边 + 白芯（两笔叠画得到描边效果）
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(self._forearm_outline)
            painter.drawLine(QPointF(0.0, 0.0), QPointF(0.0, paw_top + 2.0))
            painter.setPen(self._forearm_fill)
            painter.drawLine(QPointF(0.0, 0.0), QPointF(0.0, paw_top + 2.0))

            # 爪子（圆润白爪 + 墨黑描边）
            paw_radius = min(paw_w, _GEO_PAW_H) / 2.0
            painter.setPen(self._outline)
            painter.setBrush(self._brush_white)
            painter.drawRoundedRect(
                QRectF(-paw_w / 2.0, paw_top, paw_w, _GEO_PAW_H),
                paw_radius,
                paw_radius,
            )

            # 两个小趾凸（表现圆润的脚趾；屈指时上收，像抓住键盘）
            toe_y = paw_bottom - _GEO_TOE_R - 1.0 - c * 4.0
            for slot in (-1.0, 1.0):
                painter.drawEllipse(QRectF(
                    slot * _GEO_TOE_DX - _GEO_TOE_R,
                    toe_y,
                    _GEO_TOE_R * 2.0,
                    _GEO_TOE_R * 2.0,
                ))
        finally:
            painter.restore()

    def _draw_face(self, painter: QPainter, pose: PetPose) -> None:
        """面部：眼睛 / ω 嘴 / 腮红 / 泪点（头身融合，脸绘于团子主体之上）。"""

        painter.save()
        try:
            self._head_transform(painter, pose)

            # 腮红（在眼睛下方两侧）
            if pose.blush_alpha > 0.01:
                blush = QColor(C.COLORS["blush"])
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

            # 嘴
            self._draw_mouth(painter, pose)

            # 泪点（委屈）
            if pose.tear_alpha > 0.01:
                tear = QColor(C.COLORS["glow_blue"])
                tear.setAlphaF(min(1.0, pose.tear_alpha))
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(tear))
                painter.drawEllipse(QRectF(-_GEO_EYE_DX - 3.0, _GEO_EYE_DY + 6.0, 5.0, 6.5))
                painter.drawEllipse(QRectF(_GEO_EYE_DX - 2.0, _GEO_EYE_DY + 6.0, 5.0, 6.5))
        finally:
            painter.restore()

    def _draw_eye(
        self,
        painter: QPainter,
        side: float,
        openness: float,
        pose: PetPose,
    ) -> None:
        """单只眼睛：近黑实心椭圆（含白高光）/ 闭眼或笑眼弧线。"""

        cx = side * _GEO_EYE_DX + pose.look_x * 0.45
        cy = _GEO_EYE_DY + pose.look_y * 0.45
        openness = max(0.0, min(1.4, openness))
        curve = pose.eye_curve

        if openness < 0.18 or curve > 0.6:
            # 弧线眼（闭眼 / 笑眼 ⌒ / 委屈 ⌣）
            if curve >= 0.0:
                h = 3.6 + 5.2 * max(0.0, curve)
            else:
                h = -(3.0 + 5.2 * (-curve))
            arc = QPainterPath()
            arc.moveTo(cx - _GEO_EYE_RX, cy)
            arc.quadTo(cx, cy - h, cx + _GEO_EYE_RX, cy)
            painter.setPen(self._outline_thin)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(arc)
            return

        ry = _GEO_EYE_RY * openness
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(self._brush_ink)
        painter.drawEllipse(QRectF(cx - _GEO_EYE_RX, cy - ry, _GEO_EYE_RX * 2.0, ry * 2.0))

        # 白高光（pupil_dilate 放大高光；look_x/look_y 驱动其游移）
        hl_r = 1.5 + pose.pupil_dilate * 1.5
        painter.setBrush(self._brush_white)
        painter.drawEllipse(QRectF(
            cx - _GEO_EYE_RX * 0.35 + pose.look_x * 0.5,
            cy - ry * 0.45 + pose.look_y * 0.5,
            hl_r * 2.0,
            hl_r * 2.0,
        ))

    def _draw_mouth(self, painter: QPainter, pose: PetPose) -> None:
        """嘴型：ω 形小弯嘴 / 委屈下弯弧 / 张开小圆（可含舌头）。"""

        cy = _GEO_MOUTH_DY
        painter.setPen(self._mouth_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        if pose.mouth_open > 0.12:
            # 张开嘴（呵欠 / 兴奋 / 惊讶 / 犯困小圆嘴）
            rx = 4.5 + 5.5 * pose.mouth_open
            ry = 4.0 + 7.5 * pose.mouth_open
            painter.setBrush(self._brush_ink)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(QRectF(-rx, cy - ry * 0.35, rx * 2.0, ry * 2.0))
            if pose.tongue_show > 0.1:
                tongue = QColor(C.COLORS["blush"])
                painter.setBrush(QBrush(tongue))
                painter.drawEllipse(QRectF(
                    -rx * 0.5, cy + ry * 0.15,
                    rx * 1.0, ry * 0.85 * pose.tongue_show,
                ))
            return

        curve = pose.mouth_curve
        w = 5.5
        if curve < -0.2:
            # 委屈下弯弧 ⌢
            path = QPainterPath()
            path.moveTo(-w, cy + 1.5)
            path.quadTo(0.0, cy - 3.5 * (-curve) - 1.0, w, cy + 1.5)
            painter.drawPath(path)
            return

        # ω 形小弯嘴（中性 / 开心）：两段下弯汇于中央小峰
        dip = 2.4 + 2.2 * max(0.0, curve)
        rise = 0.8 + 1.6 * max(0.0, curve)
        path = QPainterPath()
        path.moveTo(-w, cy - rise * 0.3)
        path.quadTo(-w * 0.5, cy + dip, 0.0, cy - rise)
        path.quadTo(w * 0.5, cy + dip, w, cy - rise * 0.3)
        painter.drawPath(path)

    def _draw_zzz(self, painter: QPainter, pose: PetPose) -> None:
        """睡觉头顶的 ZZZ（FR-09 / PRD §4.5）。"""

        if pose.zzz_alpha <= 0.01:
            return
        color = QColor(C.COLORS["ink"])
        color.setAlphaF(min(1.0, max(0.0, pose.zzz_alpha)))
        painter.setPen(QPen(color, 2.4))
        font = painter.font()
        font.setPointSize(11)
        font.setBold(True)
        painter.setFont(font)
        base_x = _GEO_BODY_CX + _GEO_BODY_RX * 0.72
        base_y = _GEO_BODY_CY - _GEO_BODY_RY - 6.0 + pose.body_y
        painter.drawText(QPointF(base_x, base_y), "Z")
        painter.drawText(QPointF(base_x + 10.0, base_y - 10.0), "z")
        painter.drawText(QPointF(base_x + 18.0, base_y - 19.0), "z")

    # ------------------------------------------------------------------ #
    # 辅助
    # ------------------------------------------------------------------ #
    def _head_transform(self, painter: QPainter, pose: PetPose) -> None:
        """把绘制坐标系移动到脸部中心并施加倾斜旋转。"""

        painter.translate(
            _GEO_BODY_CX + pose.look_x * 0.3,
            _GEO_BODY_CY + pose.body_y + pose.head_y,
        )
        painter.rotate(pose.head_tilt)


__all__ = ["PetRenderer"]
