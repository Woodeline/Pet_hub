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
    "clamp_to_screens",
]
