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
from desktop_pet.core.theme import decor_for_theme, glow_for_theme

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

# 耳朵（相对体心的曲线耳）
_GEO_EAR_X: Final[float] = 27.0          # 耳根距体心横向偏移
_GEO_EAR_BASE_INSET: Final[float] = 18.0  # 耳根相对身体顶部的下沉（深埋入圆球轮廓，底边不外露）
_GEO_EAR_LEN: Final[float] = 33.0        # 耳高（补偿埋深，外露耳高与参考图相当）
_GEO_EAR_HALF_W: Final[float] = 10.0     # 耳根半宽（收窄使耳根两端都落进椭圆内）
_EAR_BOW_OUT: Final[float] = 1.2         # 耳外缘外鼓量（接近直线：与椭圆弧交角即自然三角角）
_EAR_BOW_IN: Final[float] = 3.0          # 耳内缘内凹量（猫耳内缘的经典弧）
_EAR_INNER_SCALE: Final[float] = 0.42    # 内耳半宽相对耳廓半宽的比例（留出耳廓描边呼吸感）
_EAR_INNER_LEN_FRAC: Final[float] = 0.52  # 内耳耳尖高度相对耳廓耳高的比例
_EAR_INNER_RISE: Final[float] = 4.5      # 内耳底边相对耳根线的抬高
_EAR_INNER_ALPHA: Final[int] = 200       # 内耳粉色不透明度（0-255，柔和不抢主体）

# 脸（相对体心）
_GEO_EYE_DX: Final[float] = 16.0
_GEO_EYE_DY: Final[float] = -8.0
_GEO_EYE_RX: Final[float] = 6.0
_GEO_EYE_RY: Final[float] = 6.8
_GEO_MOUTH_DY: Final[float] = 9.0
_GEO_BLUSH_DX: Final[float] = 27.0
_GEO_BLUSH_DY: Final[float] = 5.0
_GEO_BLUSH_RX: Final[float] = 9.0

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

# 接地阴影（阶段 E：视觉打磨）—— 键盘 / 鼠标下方的柔和椭圆软影，让宠物「落在桌面」
# 而非悬浮。椭圆完全落在键盘 / 鼠标各自的脏区包围盒内（见 _local_bounds 中的显式盒子）。
_GEO_GROUND_CX: Final[float] = 84.0
_GEO_GROUND_CY: Final[float] = 163.0
_GEO_GROUND_RX: Final[float] = 42.0
_GEO_GROUND_RY: Final[float] = 6.0
_GEO_GROUND_ALPHA: Final[int] = 30      # 中心不透明度（0..255，向外渐隐）
_GEO_MOUSE_SHADOW_CY: Final[float] = 170.0
_GEO_MOUSE_SHADOW_RX: Final[float] = 13.0
_GEO_MOUSE_SHADOW_RY: Final[float] = 3.5
_GEO_MOUSE_SHADOW_ALPHA: Final[int] = 22

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

        #: 当前主题的渐变停靠点（实例状态；默认 ``default`` 皮肤）。
        #: 主题**绝不**进姿态通道（``PetPose`` 全 float，见 v1.1 R1）——它是渲染器实例状态。
        self._stops: tuple[tuple[float, str], ...] = C.THEMES[C.DEFAULT_THEME]
        #: 当前皮肤名（供 ``glow_for_theme`` 派生光晕色；``set_theme`` 同步）。
        self._theme_name: str = C.DEFAULT_THEME
        #: 当前皮肤的造型装饰描述（不可变；``default`` 全空 → 不画装饰，阶段 D）。
        self._decor: C.ThemeDecor = C.THEME_DECOR[C.DEFAULT_THEME]
        #: 装饰动画相位（秒；由 UI 层每帧经 :meth:`set_decor_phase` 注入，见其说明）。
        self._decor_phase: float = 0.0

        self._outline = QPen(ink)
        self._outline.setWidthF(_STROKE_W)
        self._outline.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outline.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        #: 道具（键盘 / 鼠标）描边笔：比主体 ink 略浅，形成描边层级差（阶段 B1-3）。
        self._outline_prop = QPen(QColor(C.PROP_OUTLINE))
        self._outline_prop.setWidthF(_STROKE_W)
        self._outline_prop.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outline_prop.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._outline_thin = QPen(ink)
        self._outline_thin.setWidthF(_STROKE_W_THIN)
        self._outline_thin.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outline_thin.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        self._mouth_pen = QPen(ink)
        self._mouth_pen.setWidthF(2.2)
        self._mouth_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._mouth_pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        # 键帽顶部受光高光线（阶段 E）：半透明白细线，提亮键帽上缘 → 键盘立体感
        # （alpha 64：混合后在任何键帽色上都不会落入「近白」判定带，不污染
        #   test_hand_visibility 的前爪近白测量）
        key_hi = QColor(C.COLORS["white"])
        key_hi.setAlpha(64)
        self._key_hi_pen = QPen(key_hi)
        self._key_hi_pen.setWidthF(1.1)
        self._key_hi_pen.setCapStyle(Qt.PenCapStyle.RoundCap)

        # 趾凸细描边（阶段 E）：比主体 3.2 细一档，小元素用粗描边会糊成黑点
        self._outline_toe = QPen(ink)
        self._outline_toe.setWidthF(2.0)
        self._outline_toe.setCapStyle(Qt.PenCapStyle.RoundCap)

        # 配件描边（阶段 E）：头顶小花与全身粗描边风格统一
        self._outline_accessory = QPen(ink)
        self._outline_accessory.setWidthF(2.4)
        self._outline_accessory.setCapStyle(Qt.PenCapStyle.RoundCap)
        self._outline_accessory.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

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
    def set_theme(self, name: str) -> None:
        """切换当前主题皮肤（非法名称回落默认皮肤，不抛异常）。

        主题是**渲染器实例状态**，与 :class:`~desktop_pet.core.pet_model.PetPose`
        完全解耦 —— 因此 ``lerp_to`` / ``EXPRESSION_POSES`` 一行不用动（v1.1 R1）。

        Args:
            name: 主题名（``THEMES`` 的键之一；未知名称回落 ``default``）。
        """

        self._stops = C.THEMES.get(name, C.THEMES[C.DEFAULT_THEME])
        self._theme_name = name if name in C.THEMES else C.DEFAULT_THEME
        # 装饰描述与皮肤同步切换（未知皮肤回落 default 全空描述，不抛异常）
        self._decor = decor_for_theme(self._theme_name)

    def theme_stops(self) -> tuple[tuple[float, str], ...]:
        """返回当前主题的渐变停靠点（供托盘图标等外部取色复用）。"""

        return self._stops

    # ------------------------------------------------------------------ #
    # 主题造型装饰（阶段 D：造型元素增强）
    # ------------------------------------------------------------------ #
    #: 粒子基础下落 / 上浮速度（px/s；实际速度 = 基础 + 确定性散列 * 6.0）。
    _DECOR_BASE_SPEED: Final[float] = 8.0
    #: 粒子横向摆动基础幅度（px；实际幅度 = 基础 + 确定性散列 * 3.0）。
    _DECOR_SWAY_BASE: Final[float] = 3.0
    #: 粒子尺寸基准（逻辑画布单位；实际尺寸 = 基准 + 确定性散列 * 0.8 → [1.1, 1.9]）。
    #: 2026-09-29 张力强化：0.9/0.6 → 1.1/0.8（花瓣 / 雪花 / 枫叶整体大一号）。
    _DECOR_SIZE_BASE: Final[float] = 1.1
    _DECOR_SIZE_SPREAD: Final[float] = 0.8
    #: 粒子纵向回绕缓冲：y 落域 = [-缓冲, 画布高 + 缓冲)，出画后从另一侧回绕。
    _DECOR_WRAP_PAD: Final[float] = 12.0

    @staticmethod
    def has_decor_of(decor: C.ThemeDecor) -> bool:
        """判断一份装饰描述是否含**任何**可见元素。"""

        return not (
            decor.particle == "none"
            and decor.backdrop == "none"
            and decor.accessory == "none"
        )

    def has_decor(self) -> bool:
        """当前皮肤是否带可见装饰（``default`` 恒 False；供脏区收窄判断）。"""

        return self.has_decor_of(self._decor)

    def set_decor_phase(self, seconds: float) -> None:
        """注入装饰动画相位（秒）。

        粒子位置是 ``(decor, phase)`` 的**纯函数**：同相位必同坐标。UI 层每帧
        注入单调递增的秒数即可驱动动画；测试固定相位即可确定性复现 —— **禁止**
        在渲染路径里用运行期 ``random``（可复现性红线）。
        """

        self._decor_phase = float(seconds)

    @staticmethod
    def _decor_rand(index: int, salt: int) -> float:
        """确定性伪随机 ∈ [0, 1)：经典 ``sin`` 散列（同 (index, salt) 必同值）。"""

        v = math.sin(index * 127.1 + salt * 311.7) * 43758.5453
        return v - math.floor(v)

    def decor_particle_positions(
        self, phase: float | None = None,
    ) -> tuple[tuple[float, float, float], ...]:
        """计算当前皮肤全部粒子的 ``[(x, y, size), …]``（逻辑画布坐标）。

        位置是 ``(decor, phase)`` 的**纯函数**：基准位置由索引经确定性散列得出，
        纵向按 ``phase * speed`` 匀速运动并在画布外回绕（落域
        ``[-12, 192)``），横向叠加正弦摆动（落域 ``[-10, 170]``）。

        Args:
            phase: 显式相位（秒）；``None`` 时用内部 :meth:`set_decor_phase` 注入的相位。

        Returns:
            元组列表（``default`` / 无粒子皮肤返回空元组）。
        """

        d = self._decor
        if d.particle == "none" or d.particle_count <= 0:
            return ()
        t = self._decor_phase if phase is None else float(phase)
        span_x = _GEO_CANVAS_W - 4.0           # x 基准 ∈ [2, 158]，叠加摆动后仍不出 [-10, 170]
        span_y = _GEO_CANVAS_H                 # y 基准 ∈ [0, 180)
        wrap = self._DECOR_WRAP_PAD            # y 落域 = [-12, 192)
        period = _GEO_CANVAS_H + 2.0 * wrap    # 纵向回绕周期
        rising = False                          # 全部粒子下落（阶段 F 移除气泡上浮）
        particles: list[tuple[float, float, float]] = []
        for i in range(d.particle_count):
            base_x = 2.0 + self._decor_rand(i, 1) * span_x
            base_y = self._decor_rand(i, 2) * span_y
            speed = self._DECOR_BASE_SPEED + self._decor_rand(i, 3) * 6.0
            sway = self._DECOR_SWAY_BASE + self._decor_rand(i, 4) * 3.0
            wfreq = 0.5 + self._decor_rand(i, 5) * 0.8
            size = self._DECOR_SIZE_BASE + self._decor_rand(i, 6) * self._DECOR_SIZE_SPREAD
            # 下落 = y 随时间**增大**（屏幕坐标向下为正）：自顶端飘入、底端回绕。
            # 阶段 F 曾把符号写反导致所有粒子「向上飘」，阶段 G 修正。
            drift = -speed * t if rising else speed * t
            y = ((base_y + drift + wrap) % period + period) % period - wrap
            x = base_x + sway * math.sin(wfreq * t + self._decor_rand(i, 7) * 6.283)
            particles.append((x, y, size))
        return tuple(particles)

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

            self._draw_decor_backdrop(painter)
            self._draw_ground_shadow(painter)
            self._draw_decor_particles(painter)
            self._draw_glow(painter, pose)
            self._draw_tail(painter, pose)
            self._draw_body(painter, pose)
            self._draw_keyboard(painter, pose)
            self._draw_mouse(painter, pose)
            self._draw_arms(painter, pose)
            self._draw_face(painter, pose)
            self._draw_zzz(painter, pose)
            self._draw_decor_accessory(painter, pose)
        finally:
            painter.restore()

    def _draw_ground_shadow(self, painter: QPainter) -> None:
        """接地阴影（阶段 E）：键盘与鼠标下方的柔和椭圆软影。

        做**圆形**径向渐变后经 ``scale(1, ry/rx)`` 压扁成椭圆，使渐隐在椭圆
        边缘各方向恰好归零（环境光遮蔽感，而非中心亮斑）。
        椭圆几何受 ``_local_bounds`` 中显式盒子约束（不越出既有脏区）。
        """

        painter.save()
        try:
            painter.setPen(Qt.PenStyle.NoPen)
            for cx, cy, rx, ry, alpha in (
                (_GEO_GROUND_CX, _GEO_GROUND_CY,
                 _GEO_GROUND_RX, _GEO_GROUND_RY, _GEO_GROUND_ALPHA),
                (_GEO_MOUSE_CX, _GEO_MOUSE_SHADOW_CY,
                 _GEO_MOUSE_SHADOW_RX, _GEO_MOUSE_SHADOW_RY,
                 _GEO_MOUSE_SHADOW_ALPHA),
            ):
                center = QColor(C.COLORS["ink"])
                center.setAlpha(alpha)
                edge = QColor(C.COLORS["ink"])
                edge.setAlpha(0)
                gradient = QRadialGradient(QPointF(0.0, 0.0), rx)
                gradient.setColorAt(0.0, center)
                gradient.setColorAt(0.55, QColor(
                    center.red(), center.green(), center.blue(), alpha // 2
                ))
                gradient.setColorAt(1.0, edge)
                painter.setBrush(QBrush(gradient))
                painter.save()
                painter.translate(cx, cy)
                painter.scale(1.0, ry / rx)
                painter.drawEllipse(QPointF(0.0, 0.0), rx, rx)
                painter.restore()
        finally:
            painter.restore()

    def _draw_decor_backdrop(self, painter: QPainter) -> None:
        """布景层（最底）：春 = 垂柳（柳叶放大 + 风吹摆动）、
        夏 = 沙滩远景（沙滩 / 遮阳棚 / 太阳光效）、春节 = 远景挂灯笼、
        冬 = 远景雪山（双峰 + 远脊 + 山脚雪原）。

        三条自画布顶端垂下的柳枝用**二次贝塞尔曲线**表示（曲率连续），柳叶为
        沿枝伸展的**旋转大椭圆**（比阶段 E 放大约 1.8 倍，更醒目），整条枝与
        叶随相位做**正弦摆动**（风吹摇曳感）——摆动幅度沿枝身递增（根不动、梢最摆）。
        """

        d = self._decor
        if d.backdrop == "none":
            return
        if d.backdrop == "willow":
            self._draw_willow(painter, d)
        elif d.backdrop == "beach":
            self._draw_beach(painter, d)
        elif d.backdrop == "lantern_sky":
            self._draw_lantern_sky(painter, d)
        elif d.backdrop == "snow_mountain":
            self._draw_snow_mountain(painter, d)

    def _draw_willow(self, painter: QPainter, d: C.ThemeDecor) -> None:
        """春·垂柳：柳枝加长加密 + 柳叶放大 + 风吹摆动（2026-09-29 张力强化）。

        四条自顶端垂下的长弧枝（垂到猫身后、越过画布中线），柳叶更密更大，
        枝与叶的不透明度同步提高 —— 远景也能一眼读出「春天」。
        """

        painter.save()
        try:
            color = QColor(d.backdrop_color)
            branch_color = QColor(color)
            branch_color.setAlphaF(0.9)
            branch_pen = QPen(branch_color)
            branch_pen.setWidthF(2.8)
            branch_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(branch_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            leaf_color = QColor(color)
            leaf_color.setAlphaF(0.96)
            phase = self._decor_phase
            # 四条自顶端垂下的弧线柳枝（横向错开，长短不一、弯向各异）
            for i, (bx, drop, bend) in enumerate(
                ((22.0, 78.0, 12.0), (58.0, 92.0, -10.0), (104.0, 84.0, 10.0), (140.0, 70.0, -9.0))
            ):
                path_len = drop + self._decor_rand(i, 11) * 10.0
                mid_x = bx + bend * 1.5
                mid_y = path_len * 0.5
                end_x = bx + bend * 0.4
                # 风吹摆动：沿枝身的正弦横向偏移，幅度从根部 0 递增到梢部最大
                sway_amp = 4.0 + self._decor_rand(i, 13) * 3.0
                sway_freq = 0.9 + self._decor_rand(i, 14) * 0.6
                sway_phase = self._decor_rand(i, 15) * 6.283
                branch = QPainterPath()
                branch.moveTo(bx, 0.0)
                # 用 3 个贝塞尔控制点近似「带摆动的曲线」：中段与梢部各自横向偏移
                for seg in range(1, 7):
                    t = seg / 6.0
                    u = 1.0 - t
                    sway = sway_amp * math.sin(phase * sway_freq + sway_phase) * (t ** 1.5)
                    bx0 = bx
                    by0 = 0.0
                    bmid_x = mid_x
                    bmid_y = mid_y
                    bend_x = end_x
                    bend_y = path_len
                    # 在曲线点 (lx, ly) 上叠加横向偏移（沿曲线法线近似水平方向）
                    lx = u * u * bx0 + 2.0 * u * t * bmid_x + t * t * bend_x
                    ly = u * u * by0 + 2.0 * u * t * bmid_y + t * t * bend_y
                    branch.lineTo(lx + sway, ly)
                painter.drawPath(branch)
                # 柳叶：沿枝小椭圆（按枝的局部走向旋转），错落分布，放大更醒目
                painter.setBrush(QBrush(leaf_color))
                painter.setPen(Qt.PenStyle.NoPen)
                for k in range(7):
                    t = (k + self._decor_rand(i * 4 + k, 12)) / 7.0
                    u = 1.0 - t
                    ly = u * u * 0.0 + 2.0 * u * t * mid_y + t * t * path_len
                    lx = u * u * bx + 2.0 * u * t * mid_x + t * t * end_x
                    tangent = math.atan2(
                        2.0 * u * (mid_y - 0.0) + 2.0 * t * (path_len - mid_y),
                        2.0 * u * (mid_x - bx) + 2.0 * t * (end_x - mid_x),
                    )
                    # 叶片随风微转（相位驱动），并随摆动一起横向偏移
                    leaf_sway = sway_amp * math.sin(
                        phase * sway_freq + sway_phase
                    ) * (t ** 1.5)
                    leaf_twist = 9.0 * math.sin(phase * sway_freq * 1.3 + sway_phase + k)
                    painter.save()
                    painter.translate(lx + leaf_sway, ly)
                    painter.rotate(
                        math.degrees(tangent) + 90.0
                        + (18.0 if k % 2 == 0 else -18.0) + leaf_twist
                    )
                    painter.drawEllipse(QPointF(0.0, 4.6), 2.4, 5.4)
                    painter.restore()
                painter.setPen(branch_pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
        finally:
            painter.restore()

    def _draw_beach(self, painter: QPainter, d: C.ThemeDecor) -> None:
        """夏·沙滩远景：沙滩 + 海浪线 + 遮阳棚 + 太阳光效（2026-09-29 张力强化）。

        布景画在**最底层**（宠物背后）。遮阳棚原先放在左中景，被猫身挡住大半
        形同虚设 —— 移到**右下角**（猫与键盘的右前侧空档），完整可见；沙滩条带
        加浓，上缘补两道海浪波纹线，夏日海滨的氛围立刻成立。

        - 底部一道暖沙色条带（沙滩）+ 上缘双海浪线；
        - 右下角一顶红白条纹遮阳棚（三角形棚顶 + 立柱）；
        - 右上角一枚带光晕的太阳（加大）。
        """

        painter.save()
        try:
            sand = QColor(d.backdrop_color)
            # —— 沙滩条带（底部，加浓）——
            sand_fill = QColor(sand)
            sand_fill.setAlphaF(0.8)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(sand_fill))
            painter.drawRect(QRectF(0.0, 158.0, _GEO_CANVAS_W, 22.0))

            # —— 海浪线（沙滩上缘的两道静态波纹，浅蓝）——
            wave = QColor(C.DECOR_WAVE_BLUE)
            wave_pen = QPen(wave)
            wave_pen.setWidthF(1.6)
            wave_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(wave_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for wave_i, (wave_y, wave_span) in enumerate(((157.5, 62.0), (161.0, 46.0))):
                wave_path = QPainterPath()
                wave_start = 8.0 + wave_i * 26.0
                wave_path.moveTo(wave_start, wave_y)
                wave_seg = 4
                for wave_k in range(1, wave_seg + 1):
                    wt = wave_k / wave_seg
                    wx = wave_start + wave_span * wt
                    wy = wave_y + (3.0 if wave_k % 2 == 0 else -3.0)
                    wave_path.quadTo(
                        wave_start + wave_span * (wt - 0.5 / wave_seg), wave_y + (6.0 if wave_k % 2 == 0 else -6.0),
                        wx, wy,
                    )
                painter.drawPath(wave_path)

            # —— 遮阳棚（右下角，红白条纹三角棚顶 + 立柱，避开猫与键盘）——
            awning = QColor(C.DECOR_BEACH_AWNING)
            awning.setAlphaF(0.95)
            white = QColor(C.COLORS["white"])
            white.setAlphaF(0.95)
            pole = QColor(C.DECOR_BEACH_POLE)
            pole.setAlphaF(0.85)
            # 棚顶（扇形三角）
            painter.setBrush(QBrush(awning))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawPolygon(QPolygonF([
                QPointF(112.0, 132.0),
                QPointF(150.0, 132.0),
                QPointF(131.0, 112.0),
            ]))
            # 白色条纹
            painter.setBrush(QBrush(white))
            painter.drawPolygon(QPolygonF([
                QPointF(122.0, 132.0),
                QPointF(131.0, 132.0),
                QPointF(131.0, 113.5),
            ]))
            # 立柱
            painter.setBrush(QBrush(pole))
            painter.drawRect(QRectF(129.5, 132.0, 3.0, 30.0))

            # —— 太阳（右上角，带光晕）——
            sun_cx, sun_cy, sun_r = 138.0, 30.0, 10.0
            sun = QColor(C.DECOR_SUN_GOLD)
            # 外光晕
            halo = QRadialGradient(QPointF(sun_cx, sun_cy), sun_r * 3.6)
            halo_core = QColor(sun)
            halo_core.setAlphaF(0.6)
            halo_edge = QColor(sun)
            halo_edge.setAlpha(0)
            halo.setColorAt(0.0, halo_core)
            halo.setColorAt(1.0, halo_edge)
            painter.setBrush(QBrush(halo))
            painter.drawEllipse(
                QPointF(sun_cx, sun_cy), sun_r * 3.6, sun_r * 3.6
            )
            # 太阳本体
            painter.setBrush(QBrush(sun))
            painter.drawEllipse(QPointF(sun_cx, sun_cy), sun_r, sun_r)
        finally:
            painter.restore()

    def _draw_lantern_sky(self, painter: QPainter, d: C.ThemeDecor) -> None:
        """春节·远景挂灯笼（2026-09-29 张力强化）：顶部左右各垂下一串大红灯笼。

        灯笼加大加多（左 4 盏 / 右 3 盏）、不透明度拉满、金盖金穗同步放大，
        与烟花粒子构成浓烈的「节日夜空」层次。
        """

        painter.save()
        try:
            main = QColor(d.backdrop_color)
            accent = QColor(C.DECOR_SUN_GOLD)
            ink = QColor(C.COLORS["ink"])
            # 顶部左右各一列（x 约 20 / 140），每列 4 / 3 盏灯笼
            for col_x, lantern_count in ((20.0, 4), (140.0, 3)):
                for j in range(lantern_count):
                    ly = 16.0 + j * 26.0
                    # 细绳
                    rope = QPen(ink)
                    rope.setWidthF(0.8)
                    painter.setPen(rope)
                    painter.drawLine(
                        QPointF(col_x, ly - 12.0), QPointF(col_x, ly - 3.0)
                    )
                    # 灯体（远景尺寸 + 近实心）
                    body = QColor(main)
                    body.setAlphaF(0.95)
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(body))
                    painter.drawEllipse(QPointF(col_x, ly + 5.0), 6.0, 8.0)
                    # 灯体上的金色竖纹（灯笼骨架，两道弧）
                    rib = QColor(accent)
                    rib.setAlphaF(0.55)
                    rib_pen = QPen(rib)
                    rib_pen.setWidthF(0.9)
                    painter.setPen(rib_pen)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                    painter.drawLine(QPointF(col_x - 2.6, ly - 1.0), QPointF(col_x - 2.6, ly + 11.0))
                    painter.drawLine(QPointF(col_x + 2.6, ly - 1.0), QPointF(col_x + 2.6, ly + 11.0))
                    # 灯盖 / 灯穗
                    painter.setPen(Qt.PenStyle.NoPen)
                    painter.setBrush(QBrush(accent))
                    painter.drawRoundedRect(
                        QRectF(col_x - 3.4, ly - 4.0, 6.8, 2.8), 1.2, 1.2
                    )
                    painter.drawRoundedRect(
                        QRectF(col_x - 3.4, ly + 12.2, 6.8, 2.8), 1.2, 1.2
                    )
        finally:
            painter.restore()

    def _draw_snow_mountain(self, painter: QPainter, d: C.ThemeDecor) -> None:
        """冬·远景雪山（2026-09-29 张力强化）：最远山脊 + 双峰 + 山脚雪原。

        双峰**向两侧推开**（左峰顶 x 30→14、右峰顶 x 128→142）并加高——原先
        峰体大半被猫挡住，如今两侧山体完整可见；雪原加浓；远脊空气透视加浓。

        全部为**确定性静态几何**（无随机、无相位）——远景山脉不应运动，
        动感由其上的雪花粒子层承担。

        配色红线：判定带（x 50-74 × y 100-152）内所有落点颜色的 R 通道 < 232，
        不得污染 ``test_hand_visibility`` 的前爪近白扫描（积雪/雪原均近白，
        靠 ``DECOR_MOUNTAIN_SNOW`` 的 R=220 与预乘 alpha 保证）。
        """

        painter.save()
        try:
            body = QColor(d.backdrop_color)
            snow = QColor(C.DECOR_MOUNTAIN_SNOW)
            haze = QColor(C.DECOR_MOUNTAIN_HAZE)
            horizon = 146.0
            painter.setPen(Qt.PenStyle.NoPen)

            # ① 最远山脊（空气透视：更浅、更淡、无积雪细节），主峰后方探出
            haze.setAlphaF(0.65)
            painter.setBrush(QBrush(haze))
            painter.drawPolygon(QPolygonF([
                QPointF(48.0, horizon), QPointF(92.0, 90.0), QPointF(140.0, horizon),
            ]))

            # ② 左主峰（推开到左侧）：山体 + 右侧暗面（双面体积）+ 锯齿雪线积雪盖
            body_alpha = QColor(body)
            body_alpha.setAlphaF(0.92)
            painter.setBrush(QBrush(body_alpha))
            painter.drawPolygon(QPolygonF([
                QPointF(-14.0, horizon), QPointF(14.0, 74.0), QPointF(56.0, horizon),
            ]))
            shade = QColor(body)
            shade.setAlphaF(0.92)
            painter.setBrush(QBrush(shade.darker(112)))
            painter.drawPolygon(QPolygonF([
                QPointF(14.0, 74.0), QPointF(56.0, horizon), QPointF(20.0, horizon),
            ]))
            snow_cap = QColor(snow)
            snow_cap.setAlphaF(0.95)
            painter.setBrush(QBrush(snow_cap))
            painter.drawPolygon(QPolygonF([
                QPointF(14.0, 74.0), QPointF(31.0, 100.0), QPointF(22.0, 94.0),
                QPointF(14.0, 102.0), QPointF(5.0, 94.0), QPointF(-3.0, 98.0),
            ]))

            # ③ 右次峰（推开到右侧，更矮更远，积雪盖相应缩小）
            painter.setBrush(QBrush(body_alpha))
            painter.drawPolygon(QPolygonF([
                QPointF(112.0, horizon), QPointF(142.0, 92.0), QPointF(172.0, horizon),
            ]))
            painter.setBrush(QBrush(QColor(shade.darker(112))))
            painter.drawPolygon(QPolygonF([
                QPointF(142.0, 92.0), QPointF(172.0, horizon), QPointF(146.0, horizon),
            ]))
            painter.setBrush(QBrush(snow_cap))
            painter.drawPolygon(QPolygonF([
                QPointF(142.0, 92.0), QPointF(153.0, 108.0), QPointF(146.0, 104.0),
                QPointF(139.0, 110.0), QPointF(132.0, 105.0),
            ]))

            # ④ 山脚雪原：压平的近白雪带——与宠物接地软影衔接成「坐在雪地上」
            field = QColor(C.DECOR_MOUNTAIN_SNOW)
            field.setAlphaF(0.75)
            painter.setBrush(QBrush(field))
            painter.drawRoundedRect(QRectF(-4.0, horizon, 168.0, 40.0), 6.0, 6.0)
        finally:
            painter.restore()

    def _draw_decor_particles(self, painter: QPainter) -> None:
        """粒子层：雪（柔焦圆）/ 花瓣（斜椭圆）/ 枫叶（红黄相间大叶）/ 烟花（绽放）。

        阶段 E 层次化：每粒透明度由确定性散列差异化（0.55~0.95），雪花叠一层
        大半径低透明外晕（柔焦感）。
        阶段 F：枫叶改为**红黄相间**的双色掌形大叶（更醒目）；烟花为**周期性
        绽放**的放射线爆点（中心亮点 + 8 条射线 + 渐隐尾迹）。
        """

        d = self._decor
        if d.particle == "none" or d.particle_count <= 0:
            return
        painter.save()
        try:
            painter.setPen(Qt.PenStyle.NoPen)
            for idx, (x, y, size) in enumerate(self.decor_particle_positions()):
                alpha = 0.55 + self._decor_rand(idx, 8) * 0.4
                painter.save()
                try:
                    painter.translate(x, y)
                    color = QColor(d.particle_color)
                    if d.particle == "snow":
                        # 外晕（柔焦）+ 主圆：两层不同透明度的圆叠加
                        halo = QColor(color)
                        halo.setAlphaF(alpha * 0.35)
                        painter.setBrush(QBrush(halo))
                        painter.drawEllipse(QPointF(0, 0), 3.2 * size, 3.2 * size)
                        core = QColor(color)
                        core.setAlphaF(alpha)
                        painter.setBrush(QBrush(core))
                        painter.drawEllipse(QPointF(0, 0), 2.0 * size, 2.0 * size)
                    elif d.particle == "petal":
                        painter.rotate(38.0 * math.sin(self._decor_phase * 0.9 + x))
                        color.setAlphaF(alpha)
                        painter.setBrush(QBrush(color))
                        painter.drawEllipse(QPointF(0, 0), 3.0 * size, 1.7 * size)
                    elif d.particle == "leaf":
                        # 五裂掌形真枫叶（阶段 G 重画）：单一多边形勾出**尖裂片 +
                        # 深缺刻**轮廓（对照真实红枫叶），红/橙/金三色逐叶散列
                        # 变化 + 黄色叶脉 + 深色叶柄，下落时叠加双正弦翻滚。
                        rot = (
                            38.0 * math.sin(self._decor_phase * 1.1 + y)
                            + 24.0 * math.sin(self._decor_phase * 0.7 + x)
                        )
                        painter.rotate(rot)
                        tone = self._decor_rand(idx, 9)
                        if tone < 0.34:
                            leaf_main = QColor(color)            # 红（装饰表配置基色）
                        elif tone < 0.67:
                            leaf_main = QColor(C.DECOR_MAPLE_ORANGE)  # 橙
                        else:
                            leaf_main = QColor(C.DECOR_MAPLE_VEIN)    # 金
                        leaf_main.setAlphaF(alpha)
                        unit = (
                            (0.0, -5.0), (1.1, -3.6), (0.7, -2.9),
                            (2.6, -3.3), (2.0, -1.9), (3.6, -2.1),
                            (2.7, -0.7), (3.1, 0.8), (1.5, 0.5),
                            (1.1, 1.7), (0.4, 1.1), (0.0, 2.0),
                            (-0.4, 1.1), (-1.1, 1.7), (-1.5, 0.5),
                            (-3.1, 0.8), (-2.7, -0.7), (-3.6, -2.1),
                            (-2.0, -1.9), (-2.6, -3.3), (-0.7, -2.9),
                            (-1.1, -3.6),
                        )
                        painter.setPen(Qt.PenStyle.NoPen)
                        painter.setBrush(QBrush(leaf_main))
                        painter.drawPolygon(QPolygonF([
                            QPointF(px * size, py * size) for px, py in unit
                        ]))
                        # 黄色叶脉：一主脉 + 两对侧脉（细线，红黄相间观感）
                        vein = QPen(QColor(C.DECOR_MAPLE_VEIN))
                        vein.setWidthF(0.7)
                        vein_color = QColor(C.DECOR_MAPLE_VEIN)
                        vein_color.setAlphaF(alpha * 0.85)
                        vein.setColor(vein_color)
                        painter.setPen(vein)
                        painter.drawLine(QPointF(0.0, 1.8 * size), QPointF(0.0, -4.2 * size))
                        painter.drawLine(QPointF(0.0, 0.4 * size), QPointF(2.3 * size, -1.7 * size))
                        painter.drawLine(QPointF(0.0, 0.4 * size), QPointF(-2.3 * size, -1.7 * size))
                        # 叶柄（深色调细线，从叶底伸出）
                        stem_color = QColor(leaf_main.darker(135))
                        stem_color.setAlphaF(alpha)
                        stem = QPen(stem_color)
                        stem.setWidthF(0.9)
                        painter.setPen(stem)
                        painter.drawLine(QPointF(0.0, 2.0 * size), QPointF(0.0, 3.4 * size))
                    elif d.particle == "firework":
                        self._draw_firework(painter, idx, x, y, size, color, alpha)
                finally:
                    painter.restore()
        finally:
            painter.restore()

    def _draw_firework(
        self,
        painter: QPainter,
        idx: int,
        x: float,
        y: float,
        size: float,
        color: QColor,
        alpha: float,
    ) -> None:
        """单个烟花爆点（阶段 F）：中心亮点 + 8 条放射线 + 外圈渐隐尾迹。

        烟花「绽放」由相位周期驱动：每个爆点按 ``(idx)`` 错开相位，周期内先
        扩张（射线外伸）再淡出（透明度衰减），形成周期性绽放的夜空烟花效果。
        """

        phase = self._decor_phase
        # 每个爆点独立错开的周期（错开相位 → 交替绽放）
        period = 4.0 + self._decor_rand(idx, 20) * 2.0
        local_t = (phase / period + self._decor_rand(idx, 21)) % 1.0
        # 绽放包络：0→1 扩张、1→0 淡出（正弦半周期近似）
        bloom = math.sin(math.pi * local_t)  # 0..1..0
        if bloom < 0.05:
            return
        # 射线长度随绽放扩张，透明度随绽放衰减
        ray_len = (4.0 + 8.0 * bloom) * size
        spark_alpha = alpha * bloom
        spark = QColor(color)
        spark.setAlphaF(max(0.0, min(1.0, spark_alpha)))
        # 中心亮点
        painter.setBrush(QBrush(spark))
        painter.drawEllipse(QPointF(0.0, 0.0), 2.2 * size * bloom, 2.2 * size * bloom)
        # 8 条放射射线（固定角度，长度随绽放外伸）
        pen = QPen(spark)
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for k in range(8):
            ang = math.radians(k * 45.0 + self._decor_rand(idx, 22) * 45.0)
            tip_x = math.cos(ang) * ray_len
            tip_y = math.sin(ang) * ray_len
            # 射线尾端渐隐：从中心向外的线，起点在亮点边缘
            painter.drawLine(
                QPointF(math.cos(ang) * 1.4 * size, math.sin(ang) * 1.4 * size),
                QPointF(tip_x, tip_y),
            )
        # 外圈渐隐尾迹（低透明的小圆环残影）
        painter.setPen(Qt.PenStyle.NoPen)
        tail = QColor(color)
        tail.setAlphaF(max(0.0, min(1.0, alpha * 0.45 * bloom)))
        painter.setBrush(QBrush(tail))
        painter.drawEllipse(QPointF(0.0, 0.0), ray_len * 0.5, ray_len * 0.5)

    def _draw_decor_accessory(self, painter: QPainter, pose: PetPose) -> None:
        """配件层（最顶，画在 ZZZ 之后）：头顶小花。

        锚定于体心 ``(cx, cy + pose.body_y)``，随呼吸上下浮动（与脸一致）。
        阶段 F：仅保留「小花」一个配件（围巾 / 头侧灯笼 / 圣诞帽已随主题精简移除）。
        """

        d = self._decor
        if d.accessory == "none":
            return
        cx = _GEO_BODY_CX
        cy = _GEO_BODY_CY + pose.body_y
        painter.save()
        try:
            main = QColor(d.accessory_color)
            accent = QColor(d.accessory_accent)
            painter.setPen(self._outline_accessory)
            if d.accessory == "flower":
                # 头顶右侧五瓣小花 + 黄芯，通体墨线描边
                fx, fy = cx + 24.0, cy - 26.0
                painter.setBrush(QBrush(main))
                for k in range(5):
                    ang = math.radians(72.0 * k - 90.0)
                    painter.drawEllipse(
                        QPointF(fx + 4.2 * math.cos(ang), fy + 4.2 * math.sin(ang)),
                        2.6, 2.6,
                    )
                painter.setBrush(QBrush(accent))
                painter.drawEllipse(QPointF(fx, fy), 2.2, 2.2)
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
    def face_center(pose: PetPose) -> tuple[float, float]:
        """返回**脸部中心**的逻辑画布坐标 ``(x, y)``（阶段 B2-1）。

        供 ``PetWindow`` 把光标位置换算成「注视方向」时的基准点：以脸心为原点，
        光标偏右 → 瞳孔右移、偏上 → 上移。与 :meth:`_draw_face` 的变换基准一致
        （``_GEO_BODY_CX`` / ``_GEO_BODY_CY + pose.body_y``），故视觉上「眼睛看的就是光标」。

        Args:
            pose: 当前姿态。

        Returns:
            逻辑画布（160×180）坐标下的脸心。
        """

        return _GEO_BODY_CX, _GEO_BODY_CY + pose.body_y

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

        # --- 接地阴影（对应 _draw_ground_shadow；锚在「地面」，不随 pose 位移，
        #     故为固定盒子。椭圆完全落在键盘 / 鼠标盒子内，此处显式声明以防
        #     未来调几何时被脏区静默裁掉）---
        add(_GEO_GROUND_CX - _GEO_GROUND_RX, _GEO_GROUND_CY - _GEO_GROUND_RY,
            _GEO_GROUND_CX + _GEO_GROUND_RX, _GEO_GROUND_CY + _GEO_GROUND_RY)
        add(_GEO_MOUSE_CX - _GEO_MOUSE_SHADOW_RX,
            _GEO_MOUSE_SHADOW_CY - _GEO_MOUSE_SHADOW_RY,
            _GEO_MOUSE_CX + _GEO_MOUSE_SHADOW_RX,
            _GEO_MOUSE_SHADOW_CY + _GEO_MOUSE_SHADOW_RY)

        # --- 尾巴（包围盒直接由 _tail_spine 现算，避免手写盒与绘制脱节）---
        # 每个脊线采样点按「最大半宽 + 描边」外扩 → 保守覆盖整条尾巴（含圆帽）。
        tail_pad = _GEO_TAIL_W0 / 2.0 + _STROKE_W
        for tx, ty in PetRenderer.tail_spine(pose):
            add(tx - tail_pad, ty - tail_pad, tx + tail_pad, ty + tail_pad)

        # --- ZZZ（对应 _draw_zzz：三段文本含字体上伸部。假睡分段同样画 ZZZ 却无
        #     光晕 → 走收窄脏区，漏算会把窗口顶部的 Z 裁掉并在屏上留残影）---
        if pose.zzz_alpha > 0.01:
            zx = _GEO_BODY_CX + _GEO_BODY_RX * 0.72
            zy = _GEO_BODY_CY - _GEO_BODY_RY + 2.0 + pose.body_y
            add(zx - 4.0, zy - 36.0, zx + 36.0, zy + 4.0)

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
    def build_tray_icon(
        stops: tuple[tuple[float, str], ...] | None = None,
    ) -> QIcon:
        """用 QPainter 现画猫脸小图标（16/32px），返回 ``QIcon``。

        Args:
            stops: 渐变停靠点（跟随主题，P1）；``None`` 时使用默认皮肤
                （``THEMES[DEFAULT_THEME]``，即品牌彩虹）。
        """

        resolved = C.THEMES[C.DEFAULT_THEME] if stops is None else stops
        icon = QIcon()
        for px_size in (16, 32):
            pixmap = QPixmap(px_size, px_size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                s = px_size / 32.0
                painter.scale(s, s)
                PetRenderer._paint_tray_face(painter, resolved)
            finally:
                painter.end()
            icon.addPixmap(pixmap)
        return icon

    @staticmethod
    def _paint_tray_face(
        painter: QPainter, stops: tuple[tuple[float, str], ...],
    ) -> None:
        """在 32×32 逻辑坐标内绘制团子猫脸图标（``stops`` 为皮肤渐变停靠点）。"""

        ink = QPen(QColor(C.COLORS["ink"]))
        ink.setWidthF(2.2)
        ink.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        ink.setCapStyle(Qt.PenCapStyle.RoundCap)

        gradient = QLinearGradient(QPointF(4.0, 4.0), QPointF(28.0, 28.0))
        for pos, hexv in stops:
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
    def _body_gradient(self, x0: float, y0: float, x1: float, y1: float) -> QLinearGradient:
        """构造「左上 → 右下」的当前皮肤对角渐变。"""

        gradient = QLinearGradient(QPointF(x0, y0), QPointF(x1, y1))
        for pos, hexv in self._stops:
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
        """专注/兴奋的光晕 或 睡觉的柔光（PRD §4.2）—— 颜色随当前皮肤派生（阶段 B1-1）。

        取色交由 :func:`desktop_pet.core.theme.glow_for_theme`：
        清醒取暖端主色派生、睡觉取冷端主色派生（保住「睡觉淡蓝」语义）。
        色值**只在 core 派生**，本层不写死 hex（``test_static_constraints`` 的 AST 扫描）。
        是否睡觉以 ``pose.zzz_alpha`` 判定。
        """

        if pose.glow_alpha <= self.GLOW_ALPHA_EPSILON:
            return
        hexv = glow_for_theme(self._theme_name, sleeping=pose.zzz_alpha > 0.05)
        base = QColor(hexv)
        base.setAlphaF(min(1.0, max(0.0, pose.glow_alpha)) * 0.55)
        trans = QColor(base)
        trans.setAlpha(0)

        cx = _GEO_BODY_CX + pose.look_x * 0.2
        cy = _GEO_BODY_CY + pose.body_y
        # 半径必须收进画布：径向渐变若越过窗口边界，衰减会在窗口矩形上被硬切，
        # 屏幕上出现带直边边界的整窗色晕（观感 = 「背景不是透明的」）。取光心到
        # 四边最近距离作上界；中段停靠点补回近身浓度，保证衰减仍集中在猫周围。
        edge = min(cx, cy, _GEO_CANVAS_W - cx, _GEO_CANVAS_H - cy)
        radius = min(_GEO_BODY_RY * 2.2, edge)
        mid = QColor(base)
        mid.setAlphaF(base.alphaF() * 0.55)
        gradient = QRadialGradient(QPointF(cx, cy), radius)
        gradient.setColorAt(0.0, base)
        gradient.setColorAt(0.55, mid)
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

        颜色按身体渐变场在**根部与尾尖各自位置**取色 —— 尾巴是「全息彩虹体」
        渐变场的自然延伸：交界处与身体同色（无缝），伸向左上（场的薄荷绿端）
        时渐变到黄绿，与耳朵（同为场 0 端）形成色彩呼应。
        （此前方案：根部固定 -0.17 亮偏 → 交界处与身体出现肉眼可见的色差，
        尾巴像贴上去的黄色贴片，2026-09-29 改为场连续取色。）
        """

        spine = self.tail_spine(pose)
        path = self._tail_outline(spine)

        frac0 = self._tail_gradient_field(pose, spine[0][0], spine[0][1])
        frac1 = self._tail_gradient_field(pose, spine[-1][0], spine[-1][1])
        gradient = QLinearGradient(QPointF(*spine[0]), QPointF(*spine[-1]))
        gradient.setColorAt(0.0, QColor(self._sample_gradient(frac0)))
        gradient.setColorAt(1.0, QColor(self._sample_gradient(frac1)))

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

        # 体积感（阶段 E）：剪影内叠加「左上柔光 + 底部暗面」双层明暗，
        # 让单层对角渐变有了受光面 / 背光面 → 圆球从贴纸感变成蓬松团子感。
        painter.save()
        try:
            painter.setClipPath(silhouette)
            painter.setPen(Qt.PenStyle.NoPen)

            # 左上柔光（镜面高光的柔化版）：白 → 透明径向渐变
            hi_center = QPointF(cx - rx * 0.38, cy - ry * 0.5)
            hi_radius = rx * 0.95
            hi = QRadialGradient(hi_center, hi_radius)
            hi_color = QColor(C.COLORS["white"])
            hi_color.setAlpha(66)
            hi.setColorAt(0.0, hi_color)
            hi_end = QColor(C.COLORS["white"])
            hi_end.setAlpha(0)
            hi.setColorAt(1.0, hi_end)
            painter.setBrush(QBrush(hi))
            painter.drawEllipse(QRectF(
                hi_center.x() - hi_radius, hi_center.y() - hi_radius,
                hi_radius * 2.0, hi_radius * 2.0,
            ))

            # 底部暗面：线性渐变自中段渐入 ink 低透明度（接地投影语义）
            shade = QLinearGradient(QPointF(cx, cy), QPointF(cx, cy + ry))
            shade_mid = QColor(C.COLORS["ink"])
            shade_mid.setAlpha(0)
            shade_end = QColor(C.COLORS["ink"])
            shade_end.setAlpha(26)
            shade.setColorAt(0.0, shade_mid)
            shade.setColorAt(1.0, shade_end)
            painter.setBrush(QBrush(shade))
            painter.drawRect(QRectF(cx - rx, cy, rx * 2.0, ry))

            # 粉色内耳（在明暗叠加之后画：颜色不受柔光/暗面干扰，稳定柔粉）
            inner_ear = QColor(C.COLORS["blush"])
            inner_ear.setAlpha(_EAR_INNER_ALPHA)
            painter.setBrush(QBrush(inner_ear))
            for side in (-1.0, 1.0):
                angle = pose.ear_l_angle if side < 0 else pose.ear_r_angle
                tilt = pose.ear_l_tilt if side < 0 else pose.ear_r_tilt
                painter.drawPath(
                    self._inner_ear_path(side, angle, tilt, cx, cy, rx, ry)
                )
        finally:
            painter.restore()

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
        """单只**曲线**耳（外缘微凸、内缘微凹的猫耳），绕耳根按 ``angle``/``tilt`` 摆动。

        相比直线三角：耳尖由两段反向弯曲的二次贝塞尔收出（不再几何锐利），
        外缘顺着圆球轮廓微微外鼓、内缘向耳廓中轴微微内凹 —— 与圆润的团子
        身体放在同一套曲率语言里，消除并集交界处的「折角」粗糙感。
        """

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

        p_inner = tf(-_GEO_EAR_HALF_W, 0.0)   # 靠脸中线的耳根
        p_outer = tf(_GEO_EAR_HALF_W, 0.0)    # 远离体心的耳根
        tip = tf(0.0, -_GEO_EAR_LEN)
        # 左耳（side=-1）的 p_outer 是 p_right、右耳相反 —— 按谁更远离体心判定
        if (p_outer[0] - p_inner[0]) * side < 0.0:
            p_inner, p_outer = p_outer, p_inner

        # 外缘：耳根外 → 耳尖，控制点沿外法线外鼓 ``_EAR_BOW_OUT``
        ex, ey = tip[0] - p_outer[0], tip[1] - p_outer[1]
        seg = math.hypot(ex, ey) or 1.0
        nx, ny = ey / seg, -ex / seg          # 法线二选一，取指向体心外的那支
        if nx * side < 0.0:
            nx, ny = -nx, -ny
        ctrl_out = (
            (p_outer[0] + tip[0]) / 2.0 + nx * _EAR_BOW_OUT,
            (p_outer[1] + tip[1]) / 2.0 + ny * _EAR_BOW_OUT,
        )
        # 内缘：耳尖 → 耳根内，控制点朝耳廓中轴内凹 ``_EAR_BOW_IN``
        fx, fy = p_inner[0] - tip[0], p_inner[1] - tip[1]
        seg = math.hypot(fx, fy) or 1.0
        mx, my = -fy / seg, fx / seg          # 取指向体心的那支
        if mx * side > 0.0:
            mx, my = -mx, -my
        ctrl_in = (
            (tip[0] + p_inner[0]) / 2.0 + mx * _EAR_BOW_IN,
            (tip[1] + p_inner[1]) / 2.0 + my * _EAR_BOW_IN,
        )

        path = QPainterPath()
        path.moveTo(p_outer[0], p_outer[1])
        path.quadTo(ctrl_out[0], ctrl_out[1], tip[0], tip[1])
        path.quadTo(ctrl_in[0], ctrl_in[1], p_inner[0], p_inner[1])
        path.closeSubpath()
        return path

    def _inner_ear_path(
        self,
        side: float,
        angle: float,
        tilt: float,
        cx: float,
        cy: float,
        rx: float,
        ry: float,
    ) -> QPainterPath:
        """耳廓内的**粉色内耳**（同一摆动变换，形状为缩小的曲线耳）。

        底边抬高、整体缩小，稳定落在耳廓内部；填充柔粉无描边，
        给「贴纸剪影」加上一层生物感细节。
        """

        base_x = cx + side * _GEO_EAR_X
        base_y = cy - ry + _GEO_EAR_BASE_INSET
        ang = math.radians(side * angle + side * tilt)
        cos_a, sin_a = math.cos(ang), math.sin(ang)

        def tf(lx: float, ly: float) -> tuple[float, float]:
            return (
                base_x + lx * cos_a - ly * sin_a,
                base_y + lx * sin_a + ly * cos_a,
            )

        half_w = _GEO_EAR_HALF_W * _EAR_INNER_SCALE
        len_in = _GEO_EAR_LEN * _EAR_INNER_LEN_FRAC
        p_inner = tf(-half_w, -_EAR_INNER_RISE)
        p_outer = tf(half_w, -_EAR_INNER_RISE)
        tip = tf(0.0, -len_in)
        if (p_outer[0] - p_inner[0]) * side < 0.0:
            p_inner, p_outer = p_outer, p_inner

        ex, ey = tip[0] - p_outer[0], tip[1] - p_outer[1]
        seg = math.hypot(ex, ey) or 1.0
        nx, ny = ey / seg, -ex / seg
        if nx * side < 0.0:
            nx, ny = -nx, -ny
        ctrl_out = (
            (p_outer[0] + tip[0]) / 2.0 + nx * _EAR_BOW_OUT * _EAR_INNER_SCALE,
            (p_outer[1] + tip[1]) / 2.0 + ny * _EAR_BOW_OUT * _EAR_INNER_SCALE,
        )
        fx, fy = p_inner[0] - tip[0], p_inner[1] - tip[1]
        seg = math.hypot(fx, fy) or 1.0
        mx, my = -fy / seg, fx / seg
        if mx * side > 0.0:
            mx, my = -mx, -my
        ctrl_in = (
            (tip[0] + p_inner[0]) / 2.0 + mx * _EAR_BOW_IN * _EAR_INNER_SCALE,
            (tip[1] + p_inner[1]) / 2.0 + my * _EAR_BOW_IN * _EAR_INNER_SCALE,
        )

        path = QPainterPath()
        path.moveTo(p_outer[0], p_outer[1])
        path.quadTo(ctrl_out[0], ctrl_out[1], tip[0], tip[1])
        path.quadTo(ctrl_in[0], ctrl_in[1], p_inner[0], p_inner[1])
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

            # 键面（浅一档的深灰）+ 外圈道具描边（比主体 ink 略浅，阶段 B1-3）
            painter.setPen(self._outline_prop)
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

                    # 键帽顶部受光高光线（阶段 E）：沿上缘一道半透明白细线，
                    # 与键面受光方向一致 → 键帽有了「顶面 vs 正面」的立体分工
                    painter.setPen(self._key_hi_pen)
                    top_l = self._kb_warp(x0 + 0.8, y0 + 0.7, top_y, bot_y, top_hw, bot_hw)
                    top_r = self._kb_warp(x1 - 0.8, y0 + 0.7, top_y, bot_y, top_hw, bot_hw)
                    painter.drawLine(top_l, top_r)
                    painter.setPen(self._outline_thin)
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

    def _sample_gradient(self, frac: float) -> str:
        """按 ``frac``（0→1）在**当前皮肤**渐变停靠点间取色，用于键帽轮换 / 尾巴取色。"""

        stops = self._stops
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

            painter.setPen(self._outline_prop)
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

            # 两条趾缝短弧线（圆帽细描边；屈指时上收，像抓住键盘）
            # 阶段 E 曾用空心小圆 —— 白爪上两枚「OO」像玩具；改竖向微弧的趾缝，
            # 上端向爪中轴收拢，读作「肉垫分缝」而非「圆环贴纸」。
            seam_bottom = paw_bottom - 1.2
            seam_top = seam_bottom - 5.6 - c * 4.0
            painter.setPen(self._outline_toe)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            for slot in (-1.0, 1.0):
                base_x = slot * _GEO_TOE_DX
                seam = QPainterPath()
                seam.moveTo(base_x, seam_bottom)
                seam.quadTo(
                    base_x,
                    (seam_bottom + seam_top) / 2.0,
                    base_x - slot * 1.1,
                    seam_top,
                )
                painter.drawPath(seam)
        finally:
            painter.restore()

    def _draw_face(self, painter: QPainter, pose: PetPose) -> None:
        """面部：眼睛 / ω 嘴 / 腮红 / 泪点（头身融合，脸绘于团子主体之上）。"""

        painter.save()
        try:
            self._head_transform(painter, pose)

            # 腮红（在眼睛下方两侧；阶段 E 改径向渐变软边，消除硬边椭圆的「贴纸」感）
            if pose.blush_alpha > 0.01:
                base = QColor(C.COLORS["blush"])
                alpha = min(1.0, max(0.0, pose.blush_alpha))
                painter.setPen(Qt.PenStyle.NoPen)
                for side in (-1.0, 1.0):
                    bcx = side * _GEO_BLUSH_DX
                    bcy = _GEO_BLUSH_DY
                    radius = _GEO_BLUSH_RX * 1.15
                    blush = QRadialGradient(QPointF(bcx, bcy), radius)
                    core = QColor(base)
                    core.setAlphaF(alpha)
                    blush.setColorAt(0.0, core)
                    mid = QColor(base)
                    mid.setAlphaF(alpha * 0.85)
                    blush.setColorAt(0.55, mid)
                    rim = QColor(base)
                    rim.setAlphaF(0.0)
                    blush.setColorAt(1.0, rim)
                    painter.setBrush(QBrush(blush))
                    painter.drawEllipse(QRectF(
                        bcx - radius, bcy - radius, radius * 2.0, radius * 2.0,
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

        # 次级反光点（阶段 E）：主高光左下的一颗小亮斑，眼睛从「贴片」变「玻璃珠」
        sub_r = hl_r * 0.42
        painter.drawEllipse(QRectF(
            cx - _GEO_EYE_RX * 0.1 + pose.look_x * 0.5 - sub_r,
            cy + ry * 0.28 + pose.look_y * 0.5 - sub_r,
            sub_r * 2.0,
            sub_r * 2.0,
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
        # 纵向偏移 +2：原 -6 使最上「z」的字形顶到/越出画布顶边（睡觉与假睡两态
        # 均如此）——屏上表现为 Z 被窗口上沿削平，脏区收窄时还会留残影。
        base_y = _GEO_BODY_CY - _GEO_BODY_RY + 2.0 + pose.body_y
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
