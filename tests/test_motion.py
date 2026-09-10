"""运动 / 插值 / 周期动画 / 屏幕钳制测试（FR-13/14/21/34/36）。"""

from __future__ import annotations

import math
import random

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.pet_model import PetModel, PetPose


# --------------------------------------------------------------------------- #
# 1. 基础数学
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("v,lo,hi,expect", [(-5, 0, 1, 0), (5, 0, 1, 1), (0.5, 0, 1, 0.5)])
def test_clamp(v: float, lo: float, hi: float, expect: float) -> None:
    assert motion.clamp(v, lo, hi) == expect


def test_clamp_lo_gt_hi_returns_lo() -> None:
    assert motion.clamp(0.5, 10.0, 1.0) == 10.0


def test_lerp_clamps_t() -> None:
    assert motion.lerp(0.0, 10.0, 0.0) == 0.0
    assert motion.lerp(0.0, 10.0, 1.0) == 10.0
    assert motion.lerp(0.0, 10.0, -3.0) == 0.0
    assert motion.lerp(0.0, 10.0, 3.0) == 10.0
    assert motion.lerp(0.0, 10.0, 0.5) == pytest.approx(5.0)


def test_cycle_phase() -> None:
    assert motion.cycle_phase(0.0, 2.0) == 0.0
    assert motion.cycle_phase(0.5, 2.0) == pytest.approx(0.25)
    assert motion.cycle_phase(2.0, 2.0) == pytest.approx(1.0 % 1.0)
    assert motion.cycle_phase(5.0, 0.0) == 0.0  # period<=0 保护
    assert motion.cycle_phase(5.0, -1.0) == 0.0


def test_exponential_smoothing_t_properties() -> None:
    assert motion.exponential_smoothing_t(9.0, 0.0) == 0.0
    assert motion.exponential_smoothing_t(9.0, -1.0) == 0.0
    assert 0.0 < motion.exponential_smoothing_t(9.0, 0.033) < 1.0
    # 越大 dt → 越接近目标
    assert motion.exponential_smoothing_t(9.0, 0.1) > motion.exponential_smoothing_t(9.0, 0.01)


def test_exponential_smoothing_is_frame_rate_independent() -> None:
    """FR-34 核心承诺：1s 内无论 30fps 还是 60fps，逼近程度应一致。"""

    def remaining_after(k: float, dt: float, steps: int) -> float:
        r = 1.0
        for _ in range(steps):
            r *= 1.0 - motion.exponential_smoothing_t(k, dt)
        return r

    k = C.POSE_SMOOTH_K
    r30 = remaining_after(k, 1.0 / 30, 30)
    r60 = remaining_after(k, 1.0 / 60, 60)
    r_exact = math.exp(-k * 1.0)
    assert r30 == pytest.approx(r_exact, rel=1e-6)
    assert r60 == pytest.approx(r_exact, rel=1e-6)
    assert r30 == pytest.approx(r60, rel=1e-9)


# --------------------------------------------------------------------------- #
# 2. 缓动函数边界（t=0 / t=1 / 越界）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "func",
    [motion.ease_in_out, motion.ease_out_cubic, motion.ease_out_back, motion.ease_out_bounce],
)
def test_easing_bounds(func) -> None:
    assert func(0.0) == pytest.approx(0.0, abs=1e-9)
    assert func(1.0) == pytest.approx(1.0, abs=1e-9)
    # 越界安全钳制
    assert func(-5.0) == pytest.approx(0.0, abs=1e-9)
    assert func(5.0) == pytest.approx(1.0, abs=1e-9)


def test_ease_out_back_overshoots_within_reason() -> None:
    peak = max(motion.ease_out_back(t / 100.0) for t in range(101))
    assert peak > 1.0  # 存在过冲


# --------------------------------------------------------------------------- #
# 3. 周期动画（帧率无关：只依赖 now）
# --------------------------------------------------------------------------- #
def test_periodic_functions_depend_only_on_now() -> None:
    # 相同 now → 相同值，与调用次数无关
    a = motion.breath_offset(1.234)
    b = motion.breath_offset(1.234)
    assert a == b


def test_breath_offset_range() -> None:
    vals = [motion.breath_offset(t / 50.0) for t in range(200)]
    assert max(vals) <= C.BREATH_AMPLITUDE_PX + 1e-9
    assert min(vals) >= -C.BREATH_AMPLITUDE_PX - 1e-9


def test_tail_angle_range() -> None:
    vals = [motion.tail_angle(t / 50.0) for t in range(200)]
    assert max(abs(v) for v in vals) <= C.TAIL_AMPLITUDE_DEG + 1e-9


def test_ear_twitch_non_negative_and_zeros_in_second_half() -> None:
    period = C.EAR_TWITCH_MIN_S
    # 相位后半段（0.5~1.0）恒为 0
    t = period * 0.75
    assert motion.ear_twitch(t, period) == 0.0
    # 前半段非负
    assert motion.ear_twitch(period * 0.25, period) >= 0.0


def test_blink_curve_shape() -> None:
    dur = C.BLINK_DURATION_S
    assert motion.blink_curve(0.0, dur) == 1.0
    assert motion.blink_curve(dur, dur) == 1.0
    assert motion.blink_curve(-1.0, dur) == 1.0
    assert motion.blink_curve(dur / 2.0, dur) == pytest.approx(0.0)  # 完全闭合
    assert 0.0 <= motion.blink_curve(dur * 0.25, dur) <= 1.0
    assert motion.blink_curve(0.01, 0.0) == 1.0  # duration<=0 保护


def test_random_interval_bounds() -> None:
    rng = random.Random(7)
    for _ in range(100):
        v = motion.random_interval(2.0, 4.0, rng)
        assert 2.0 <= v <= 4.0
    assert motion.random_interval(3.0, 1.0) == 3.0  # hi<=lo → lo


# --------------------------------------------------------------------------- #
# 4. 屏幕钳制（FR-21 / FR-36）
# --------------------------------------------------------------------------- #
def test_clamp_empty_screens_returns_input() -> None:
    assert motion.clamp_to_screens(50, 60, 160, 180, []) == (50, 60)


def test_clamp_inside_single_screen_unchanged() -> None:
    screens = [(0, 0, 1920, 1080)]
    assert motion.clamp_to_screens(100, 200, 160, 180, screens) == (100, 200)


def test_clamp_negative_coords_into_screen() -> None:
    """窗口部分越界（左上角为负）→ 钳入屏幕左上角 (0,0)。"""

    screens = [(0, 0, 1920, 1080)]
    x, y = motion.clamp_to_screens(-50, -50, 160, 180, screens)
    assert (x, y) == (0, 0)


def test_clamp_oversized_coords_into_screen() -> None:
    """窗口仍与屏幕相交但超出右下边界 → 钳入右下可见区。"""

    screens = [(0, 0, 1920, 1080)]
    x, y = motion.clamp_to_screens(1800, 1000, 160, 180, screens)
    assert (x, y) == (1920 - 160, 1080 - 180)


def test_clamp_fully_offscreen_falls_back_to_visible_area() -> None:
    """完全脱离所有屏幕（毫无交集）→ 回落主屏右下可见区（§9.3）。"""

    screens = [(0, 0, 1920, 1080)]
    x, y = motion.clamp_to_screens(-500, -500, 160, 180, screens)
    assert (x, y) == (
        1920 - 160 - C.DEFAULT_MARGIN_PX,
        1080 - 180 - C.DEFAULT_MARGIN_PX,
    )


def test_clamp_no_intersection_falls_back_to_primary_bottom_right() -> None:
    screens = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
    fallback = (0, 0, 1920, 1080)
    x, y = motion.clamp_to_screens(99999, 99999, 160, 180, screens, fallback)
    assert (x, y) == (1920 - 160 - C.DEFAULT_MARGIN_PX, 1080 - 180 - C.DEFAULT_MARGIN_PX)


def test_clamp_chooses_screen_with_largest_intersection() -> None:
    # 副屏在左侧（负坐标，常见于左副屏布局）
    screens = [(0, 0, 1920, 1080), (-1920, 0, 1920, 1080)]
    x, y = motion.clamp_to_screens(-1900, 100, 160, 180, screens)
    assert x == -1900  # 完全落在副屏内，保持不动
    assert y == 100


def test_clamp_window_larger_than_screen() -> None:
    screens = [(0, 0, 100, 100)]
    # 窗口 500x500 远大于屏幕：不应崩溃，左上角贴屏
    x, y = motion.clamp_to_screens(50, 50, 500, 500, screens)
    assert (x, y) == (0, 0)


def test_clamp_zero_size_screen_does_not_crash() -> None:
    """退化屏幕（0×0）不应崩溃，返回整数坐标。"""

    screens = [(0, 0, 0, 0)]
    result = motion.clamp_to_screens(10, 10, 160, 180, screens)
    assert isinstance(result, tuple) and len(result) == 2
    assert all(isinstance(v, int) for v in result)


def test_clamp_multi_screen_boundary() -> None:
    screens = [(0, 0, 1920, 1080), (1920, 0, 1280, 1024)]
    # 窗口大部分在主屏、右侧越界 → 钳入主屏右边界
    x, y = motion.clamp_to_screens(1800, 500, 160, 180, screens)
    assert x == 1920 - 160
    assert y == 500


# --------------------------------------------------------------------------- #
# 5. 姿态插值：收敛性 & 帧率无关（经 PetModel 端到端验证）
# --------------------------------------------------------------------------- #
def test_interpolate_pose_converges_to_target() -> None:
    start = PetModel.pose_for_expression(C.Expression.HAPPY)
    target = PetModel.pose_for_expression(C.Expression.SLEEPING)
    cur = PetPose(**{f: getattr(start, f) for f in vars(start)})
    for _ in range(400):
        cur = motion.interpolate_pose(cur, target, motion.exponential_smoothing_t(C.POSE_SMOOTH_K, 0.033))
    assert cur.zzz_alpha == pytest.approx(target.zzz_alpha, abs=1e-3)
    assert cur.glow_alpha == pytest.approx(target.glow_alpha, abs=1e-3)


def _run_model(fps: int, seconds: float, expression: C.Expression, live_clock: bool = True):
    model = PetModel()
    model.set_base_expression(expression)
    model.set_expression(expression, 0.0)  # 清空临时表情，避免插队干扰
    dt = 1.0 / fps
    steps = int(round(fps * seconds))
    now = 0.0
    for _ in range(steps):
        now = (now + dt) if live_clock else 1.0
        model.update(dt, now)
    return model.pose()


def _max_pose_diff(a, b) -> tuple[float, str]:
    worst_diff = 0.0
    worst_field = ""
    for field in vars(a):
        d = abs(getattr(a, field) - getattr(b, field))
        if d > worst_diff:
            worst_diff = d
            worst_field = field
    return worst_diff, worst_field


def test_model_frame_rate_independent_frozen_clock() -> None:
    """目标姿态恒定时，30fps 与 60fps 逼近结果应**精确一致**（FR-34 核心承诺）。"""

    p30 = _run_model(30, 1.0, C.Expression.SURPRISED, live_clock=False)
    p60 = _run_model(60, 1.0, C.Expression.SURPRISED, live_clock=False)
    diff, field = _max_pose_diff(p30, p60)
    assert diff < 1e-6, f"恒定时帧率无关性被破坏：{field} 差 {diff}"


def test_model_frame_rate_independent_live_clock() -> None:
    """时钟推进（含呼吸/尾巴周期）时，30 vs 60fps 差值应远小于通道振幅。

    说明：周期项本身是帧率无关的（只依赖绝对 now）；此处差值来自**离散采样的
    固有相位差**（对 0~1s 内变化的信号，30 与 60 个采样点的加权结果略有不同），
    属于采样特性而非实现缺陷。实测差值在 14° 尾摆振幅下 < 1°。
    """

    p30 = _run_model(30, 1.0, C.Expression.SURPRISED)
    p60 = _run_model(60, 1.0, C.Expression.SURPRISED)
    diff, field = _max_pose_diff(p30, p60)
    print(f"\n[fri] 30fps vs 60fps 最大通道差 = {diff:.4f}（通道={field}）")
    assert diff < 0.25, f"帧率差异过大：{field} 差 {diff}"


def test_model_pose_survives_negative_dt() -> None:
    model = PetModel()
    model.update(-1.0, 5.0)  # 不应崩溃
    assert isinstance(model.pose(), PetPose)
