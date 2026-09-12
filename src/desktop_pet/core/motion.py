"""core.motion —— 缓动 / 插值 / 周期动画 / 屏幕钳制的**纯计算**工具。

**本模块禁止 import 任何图形界面（Qt/GUI）库。**

约定（架构 §9.4）：
- 时间统一为秒（float），``now`` 由调用方注入。
- 周期动画一律用 ``phase = (now / period) mod 1`` 保证**帧率无关**。
- 姿态插值用 ``t = 1 - exp(-k*dt)`` 的**帧率无关**平滑形式，禁止用固定 ``t=k``。
"""

from __future__ import annotations

import math
import random
from typing import TYPE_CHECKING, Final, Sequence

from desktop_pet.core import constants as C

if TYPE_CHECKING:  # 仅类型检查期导入，避免与 pet_model 形成运行时循环依赖
    from desktop_pet.core.pet_model import PetPose

_TWO_PI: Final[float] = 2.0 * math.pi


# --------------------------------------------------------------------------- #
# 基础数学
# --------------------------------------------------------------------------- #
def clamp(value: float, lo: float, hi: float) -> float:
    """把 ``value`` 限制在 ``[lo, hi]`` 区间。``lo > hi`` 时返回 ``lo``。"""

    if lo > hi:
        return lo
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def lerp(a: float, b: float, t: float) -> float:
    """线性插值：``t=0`` 取 ``a``，``t=1`` 取 ``b``（``t`` 会被钳制到 [0,1]）。"""

    tt = clamp(t, 0.0, 1.0)
    return a + (b - a) * tt


def cycle_phase(now: float, period: float) -> float:
    """返回周期相位 ``[0, 1)``；``period <= 0`` 时返回 0。"""

    if period <= 0.0:
        return 0.0
    return (now / period) % 1.0


def exponential_smoothing_t(k: float, dt: float) -> float:
    """帧率无关插值系数 ``t = 1 - exp(-k*dt)``。

    Args:
        k: 平滑速率（越大越快逼近目标）。
        dt: 帧间隔（秒）。

    Returns:
        ``[0, 1)`` 的插值系数。``dt<=0`` 返回 0。
    """

    if dt <= 0.0:
        return 0.0
    return 1.0 - math.exp(-max(0.0, k) * dt)


# --------------------------------------------------------------------------- #
# 缓动函数（全部归属本模块，ui 层禁止自定义缓动）
# --------------------------------------------------------------------------- #
def ease_in_out(t: float) -> float:
    """正弦型缓入缓出。"""

    tt = clamp(t, 0.0, 1.0)
    return -(math.cos(math.pi * tt) - 1.0) / 2.0


def smoothstep(t: float) -> float:
    """三次平滑阶跃 ``3t²-2t³``：两端一阶导为 0，用于「缓起缓止」的过渡。

    与 :func:`ease_in_out` 的区别：``smoothstep`` 是多项式、值域严格 ``[0,1]``、
    ``t<=0 → 0`` / ``t>=1 → 1``，适合做**参数归一化**（如尾巴转向量沿脊线的分布）。
    """

    tt = clamp(t, 0.0, 1.0)
    return tt * tt * (3.0 - 2.0 * tt)


def ease_out_cubic(t: float) -> float:
    """三次缓出。"""

    tt = clamp(t, 0.0, 1.0)
    return 1.0 - (1.0 - tt) ** 3


def ease_out_back(t: float, overshoot: float = 1.70158) -> float:
    """带轻微过冲的缓出（用于弹跳/被拎起回落）。"""

    tt = clamp(t, 0.0, 1.0)
    c3 = overshoot + 1.0
    return 1.0 + c3 * (tt - 1.0) ** 3 + overshoot * (tt - 1.0) ** 2


def ease_out_bounce(t: float) -> float:
    """轻量弹跳缓出（点击弹跳用）。"""

    tt = clamp(t, 0.0, 1.0)
    n1 = 7.5625
    d1 = 2.75
    if tt < 1.0 / d1:
        return n1 * tt * tt
    if tt < 2.0 / d1:
        tt -= 1.5 / d1
        return n1 * tt * tt + 0.75
    if tt < 2.5 / d1:
        tt -= 2.25 / d1
        return n1 * tt * tt + 0.9375
    tt -= 2.625 / d1
    return n1 * tt * tt + 0.984375


# --------------------------------------------------------------------------- #
# 姿态插值
# --------------------------------------------------------------------------- #
def interpolate_pose(current: "PetPose", target: "PetPose", t: float) -> "PetPose":
    """在 ``current`` 与 ``target`` 之间按系数 ``t`` 插值，返回新的姿态对象。"""

    return current.lerp_to(target, clamp(t, 0.0, 1.0))


# --------------------------------------------------------------------------- #
# 周期动画（帧率无关，phase = (now / period) mod 1）
# --------------------------------------------------------------------------- #
def breath_offset(
    now: float,
    period: float = C.BREATH_PERIOD_S,
    amplitude: float = C.BREATH_AMPLITUDE_PX,
) -> float:
    """呼吸起伏偏移（正负摆动的位移，单位像素）。"""

    return amplitude * math.sin(_TWO_PI * cycle_phase(now, period))


def tail_angle(
    now: float,
    period: float = C.TAIL_MIN_S,
    amplitude: float = C.TAIL_AMPLITUDE_DEG,
) -> float:
    """尾巴摆动角度偏移（度），正弦摆动。"""

    return amplitude * math.sin(_TWO_PI * cycle_phase(now, period))


def ear_twitch(
    now: float,
    period: float = C.EAR_TWITCH_MIN_S,
    amplitude: float = C.EAR_TWITCH_AMPLITUDE_DEG,
) -> float:
    """耳朵偶发抖动角度（度）。使用非对称周期使其看起来"偶发"。"""

    phase = cycle_phase(now, period)
    # 只在相位前半段抖动，且幅度按 sin 包络衰减，制造自然偶发感
    if phase < 0.5:
        envelope = math.sin(math.pi * (phase / 0.5))
        return amplitude * envelope
    return 0.0


def blink_curve(elapsed: float, duration: float = C.BLINK_DURATION_S) -> float:
    """返回眼睛"睁开度"系数：常态 ``1.0``，眨眼过程 ``1 → 0 → 1``。

    Args:
        elapsed: 自本次眨眼开始的秒数。
        duration: 单次眨眼总时长。
    """

    if duration <= 0.0 or elapsed <= 0.0 or elapsed >= duration:
        return 1.0
    progress = elapsed / duration  # 0..1
    return abs(2.0 * progress - 1.0)


def look_around_offset(
    now: float,
    period: float = C.LOOK_AROUND_PERIOD_S,
    amplitude: float = C.LOOK_AROUND_AMPLITUDE_PX,
) -> float:
    """空闲左右张望时瞳孔水平偏移（像素），低频正弦。"""

    return amplitude * math.sin(_TWO_PI * cycle_phase(now, period))


def random_interval(lo: float, hi: float, rng: random.Random | None = None) -> float:
    """返回 ``[lo, hi]`` 区间内的随机秒数；``hi <= lo`` 时返回 ``lo``。"""

    if hi <= lo:
        return lo
    generator = rng if rng is not None else random
    return generator.uniform(lo, hi)


# --------------------------------------------------------------------------- #
# 点 / 折线几何（供「鼠标靠近尾巴」的亲近度判定；纯计算，无 Qt 依赖）
# --------------------------------------------------------------------------- #
def point_segment_distance(
    px: float, py: float, ax: float, ay: float, bx: float, by: float,
) -> float:
    """点 ``P`` 到线段 ``AB`` 的最短距离（``AB`` 退化为点时取到该点的距离）。"""

    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if denom <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = clamp(((px - ax) * dx + (py - ay) * dy) / denom, 0.0, 1.0)
    return math.hypot(px - (ax + dx * t), py - (ay + dy * t))


def _nearest_segment(
    px: float, py: float, pts: Sequence[tuple[float, float]],
) -> tuple[float, tuple[float, float], tuple[float, float]]:
    """点 ``P`` 到折线的最近线段：``(距离, 最近点, 线段方向)``。

    折线不足两点时返回 ``(0.0, (px, py), (0.0, 0.0))``。
    """

    if len(pts) < 2:
        return 0.0, (px, py), (0.0, 0.0)

    best_distance = float("inf")
    best_point = (pts[0][0], pts[0][1])
    best_dir = (0.0, 0.0)
    for i in range(len(pts) - 1):
        ax, ay = pts[i]
        bx, by = pts[i + 1]
        dx, dy = bx - ax, by - ay
        denom = dx * dx + dy * dy
        if denom <= 1e-12:
            t = 0.0
        else:
            t = clamp(((px - ax) * dx + (py - ay) * dy) / denom, 0.0, 1.0)
        cx, cy = ax + dx * t, ay + dy * t
        distance = math.hypot(px - cx, py - cy)
        if distance < best_distance:
            best_distance = distance
            best_point = (cx, cy)
            best_dir = (dx, dy)
    return best_distance, best_point, best_dir


def polyline_proximity(
    px: float, py: float, pts: Sequence[tuple[float, float]],
) -> tuple[float, float]:
    """点 ``P`` 到折线的 ``(最短距离, 有符号侧别)``。

    侧别取自「最近线段方向 × (P - 最近点)」的叉积符号，因此**与折线朝向绑定**：

    * 画布坐标（``y`` 向下）中，若折线沿 ``+x`` 前进，则 ``+1`` 表示 ``P`` 在其
      **下方**（``y`` 较大侧），``-1`` 表示上方；折线掉头时符号随之翻转。
    * 点恰好落在折线上、或折线不足两点时返回 ``0.0``。

    注意：本函数只回答"离多近、在哪一侧"。**该往哪躲**由
    :func:`flee_direction` 决定（对弯曲的尾巴，靠侧别再取反是错的 —— 见其文档）。
    """

    if len(pts) < 2:
        return 0.0, 0.0

    distance, (cx, cy), (dx, dy) = _nearest_segment(px, py, pts)
    cross = dx * (py - cy) - dy * (px - cx)
    # 用最小分辨率判断退化，避免浮点噪声把"恰好在线上"判成某一侧
    if abs(cross) <= 1e-9:
        return distance, 0.0
    return distance, (1.0 if cross > 0.0 else -1.0)


def polyline_centroid(pts: Sequence[tuple[float, float]]) -> tuple[float, float]:
    """折线所有采样点的算术平均（形状重心，用作"尾巴在哪边"的代表点）。"""

    if not pts:
        return 0.0, 0.0
    return (
        sum(p[0] for p in pts) / len(pts),
        sum(p[1] for p in pts) / len(pts),
    )


def flee_direction(
    px: float, py: float, pts: Sequence[tuple[float, float]], lift: float = 0.0,
) -> tuple[float, float]:
    """光标 ``P`` 处，尾巴应当**逃离**的单位方向。

    取「光标 → 折线重心」的单位向量，再按需叠加一个**向上偏置** ``lift``。

    为什么不用"最近点侧别取反"：尾巴是**弯曲**的，整条绕根部旋转只能让各点沿切线
    移动；光标落在径向或斜上方时，切线方向与"远离"方向几乎垂直甚至相反，尾巴会
    越躲越近（实测 5 个方位里 4 个 Δ 为负）。沿「光标指向尾巴」的反方向整体让开，则
    对任意方位都至少不会靠近，且形状不乱。

    为什么要上翘偏置：纯粹水平逃开时，若尾巴已经把画面左沿顶住（本宠物尾巴就贴边），
    水平方向无路可退，反应会退化成"完全不动"。猫受惊时尾巴本就会**上翘**，加一点
    向上分量既更像猫，又在垂直方向留出空间。偏置只在光标**不在尾巴上方**时施加
    （此时向上必然也是远离），光标在上方时保持纯向下逃离，不会自相矛盾。

    Args:
        px: 光标 x（逻辑画布坐标）。
        py: 光标 y。
        pts: 折线采样点（根 → 尖）。
        lift: 向上偏置量（``0`` = 不加）。典型值 0.3~0.4。

    Returns:
        ``(ux, uy)`` 单位向量；折线不足两点或光标与重心重合时返回 ``(0.0, 0.0)``。
    """

    if len(pts) < 2:
        return 0.0, 0.0
    cx, cy = polyline_centroid(pts)
    vx, vy = cx - px, cy - py
    norm = math.hypot(vx, vy)
    if norm <= 1e-9:
        return 0.0, 0.0
    ux, uy = vx / norm, vy / norm

    if lift > 0.0 and uy <= 0.0:
        # uy <= 0 → 光标与尾巴重心齐平或更低 → 向上一定也是远离
        lx, ly = ux, uy - lift
        lifted = math.hypot(lx, ly)
        if lifted > 1e-9:
            return lx / lifted, ly / lifted
    return ux, uy


def ramp_weights(n: int, power: float = 2.0) -> tuple[float, ...]:
    """``n`` 个采样点的 ``0 → 1`` 单调递增权重（``w_k = (k / (n-1)) ** power``）。

    用于把尾巴的**位移按沿脊线的位置分配**：根部（``k = 0``）权重恒为 ``0``，
    尾巴因此始终"长在"身体上；越靠尾尖让开得越多。
    权重本身光滑单调，叠加到光滑脊线上不会引入折点。
    """

    if n <= 1:
        return (0.0,)
    last = float(n - 1)
    return tuple((k / last) ** power for k in range(n))


def tail_evade_amount(distance: float, near: float, far: float) -> float:
    """光标到尾巴的距离 → 避让强度 ``[0, 1]``。

    * ``distance <= near`` → ``1.0``（视为碰到尾巴）
    * ``distance >= far``  → ``0.0``（完全无反应）
    * 其间用 :func:`smoothstep` 反向平滑过渡（无硬边跳变）
    """

    if far <= near:
        return 1.0 if distance <= near else 0.0
    if distance <= near:
        return 1.0
    if distance >= far:
        return 0.0
    return 1.0 - smoothstep((distance - near) / (far - near))


# --------------------------------------------------------------------------- #
# 多显示器 / 屏幕越界钳制（FR-21 / FR-36）
# --------------------------------------------------------------------------- #
def _intersection_area(
    x: float,
    y: float,
    w: float,
    h: float,
    sx: float,
    sy: float,
    sw: float,
    sh: float,
) -> float:
    """返回窗口矩形与屏幕矩形的相交面积。"""

    ix = min(x + w, sx + sw) - max(x, sx)
    iy = min(y + h, sy + sh) - max(y, sy)
    if ix <= 0.0 or iy <= 0.0:
        return 0.0
    return ix * iy


def clamp_to_screens(
    x: float,
    y: float,
    w: float,
    h: float,
    screens: Sequence[tuple[int, int, int, int]],
    fallback: tuple[int, int, int, int] | None = None,
) -> tuple[int, int]:
    """把窗口左上角坐标钳制到可见屏幕区域内。

    规则（架构 §9.3）：
    - 若窗口与某块屏幕有交集 → 选择交集最大的屏幕并把窗口完整钳入其范围。
    - 若完全不与任何屏幕相交（屏幕被移除 / 坐标越界）→ 回落到 ``fallback``
      （通常为主屏）的右下角内缩 ``DEFAULT_MARGIN_PX``。

    Args:
        x, y: 窗口左上角坐标。
        w, h: 窗口宽高。
        screens: 屏幕几何列表 ``[(x, y, w, h), ...]``。
        fallback: 无交集时的回落屏幕几何（主屏）。

    Returns:
        钳制后的 ``(x, y)`` 整数坐标。
    """

    if not screens:
        return int(x), int(y)

    best_screen: tuple[int, int, int, int] | None = None
    best_area = 0.0
    for screen in screens:
        area = _intersection_area(x, y, w, h, *screen)
        if area > best_area:
            best_area = area
            best_screen = screen

    if best_screen is None or best_area <= 0.0:
        target = fallback if fallback is not None else screens[0]
        sx, sy, sw, sh = target
        fx = int(sx + sw - w - C.DEFAULT_MARGIN_PX)
        fy = int(sy + sh - h - C.DEFAULT_MARGIN_PX)
        return fx, fy

    sx, sy, sw, sh = best_screen
    lo_x, hi_x = sx, max(sx, sx + sw - w)
    lo_y, hi_y = sy, max(sy, sy + sh - h)
    cx = int(clamp(x, lo_x, hi_x))
    cy = int(clamp(y, lo_y, hi_y))
    return cx, cy


__all__ = [
    "clamp",
    "lerp",
    "cycle_phase",
    "exponential_smoothing_t",
    "ease_in_out",
    "smoothstep",
    "ease_out_cubic",
    "ease_out_back",
    "ease_out_bounce",
    "interpolate_pose",
    "breath_offset",
    "tail_angle",
    "ear_twitch",
    "blink_curve",
    "look_around_offset",
    "random_interval",
    "point_segment_distance",
    "polyline_proximity",
    "polyline_centroid",
    "flee_direction",
    "ramp_weights",
    "tail_evade_amount",
    "clamp_to_screens",
]
