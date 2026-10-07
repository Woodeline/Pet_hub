"""工程师自测：耳尾弹簧物理 —— motion.spring_step 纯函数 + PetModel 集成。

覆盖：
1. spring_step：dt<=0 原样返回、欠阻尼过零振荡、过阻尼单调收敛、收敛到目标。
2. 帧率无关（FR-34）：同一物理时长在 30/60/8 fps 步进下终态一致
   （固定子步长 1/120 使其精确成立）。
3. PetModel 加性振荡：无激励时振荡恒为 0（姿态与旧路径逐位一致，零回归）；
   激励后偏离基线、随时间收敛回基线；限幅生效。
4. 门控：reduce_motion 不激励不积分；拖拽拎起直通清零。

core 零时钟约定：全部推进由注入的 dt 序列驱动，不取真实时钟。
"""

from __future__ import annotations

import math

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.pet_model import PetModel

# --------------------------------------------------------------------------- #
# spring_step 纯函数
# --------------------------------------------------------------------------- #
def test_spring_step_zero_dt_returns_state() -> None:
    """dt<=0：状态原样返回（不推进）。"""

    assert motion.spring_step(1.5, -2.0, 0.0, 0.0, k=120.0, zeta=0.45) == (1.5, -2.0)
    assert motion.spring_step(1.5, -2.0, 0.0, -0.1, k=120.0, zeta=0.45) == (1.5, -2.0)


def test_spring_step_underdamped_crosses_zero() -> None:
    """欠阻尼：从正位移静止释放 → 过零（变号）后振荡衰减。"""

    x, v = 10.0, 0.0
    crossed = False
    for _ in range(600):  # 10s @ 60fps
        x, v = motion.spring_step(x, v, 0.0, 1.0 / 60.0, k=C.EAR_SPRING_K, zeta=C.EAR_SPRING_ZETA)
        if x < 0.0:
            crossed = True
            break
    assert crossed, "欠阻尼弹簧应过零振荡"


def test_spring_step_overdamped_never_crosses() -> None:
    """过阻尼（zeta=2）：单调收敛，永不过零。"""

    x, v = 10.0, 0.0
    for _ in range(1200):  # 20s @ 60fps
        x, v = motion.spring_step(x, v, 0.0, 1.0 / 60.0, k=C.EAR_SPRING_K, zeta=2.0)
        assert x > 0.0
    assert x < 0.1, "过阻尼应收敛"


def test_spring_step_converges_to_target() -> None:
    """有初速度的激励：10s 后收敛到目标附近（|x|、|v| 足够小）。"""

    x, v = 0.0, 200.0
    for _ in range(600):
        x, v = motion.spring_step(x, v, 0.0, 1.0 / 60.0, k=C.TAIL_SPRING_K, zeta=C.TAIL_SPRING_ZETA)
    assert abs(x) < 1e-3
    assert abs(v) < 1e-3


@pytest.mark.parametrize("fps", [30, 60, 8])
def test_spring_step_frame_rate_independence(fps: int) -> None:
    """同一物理时长、不同帧率步进 → 终态一致（FR-34；子步长 1/120 精确整除）。"""

    def simulate(step_dt: float, seconds: float) -> tuple[float, float]:
        x, v = 0.0, 180.0
        steps = round(seconds / step_dt)
        for _ in range(steps):
            x, v = motion.spring_step(
                x, v, 0.0, step_dt, k=C.EAR_SPRING_K, zeta=C.EAR_SPRING_ZETA
            )
        return x, v

    reference = simulate(1.0 / 120.0, 6.0)
    result = simulate(1.0 / fps, 6.0)
    assert result[0] == pytest.approx(reference[0], abs=1e-9)
    assert result[1] == pytest.approx(reference[1], abs=1e-9)


# --------------------------------------------------------------------------- #
# PetModel 集成（加性振荡）
# --------------------------------------------------------------------------- #
def _run(model: PetModel, frames: int, dt: float = 1.0 / 30.0) -> None:
    for _ in range(frames):
        model.update(dt, 0.0)


def test_no_impulse_pose_identical_to_legacy() -> None:
    """无激励：振荡状态恒为 0，姿态通道与旧路径逐位一致（零回归）。"""

    model = PetModel()
    _run(model, 120)
    assert model._ear_l_osc == 0.0
    assert model._ear_r_osc == 0.0
    assert model._tail_osc == 0.0


def test_impulse_cap() -> None:
    """激励限幅：超大位移输入被钳到 ``SPRING_IMPULSE_CAP_DEG_S``。"""

    model = PetModel()
    model.add_impulse(1000.0, 0.0)
    assert model._ear_l_vel == pytest.approx(-C.SPRING_IMPULSE_CAP_DEG_S)
    assert model._tail_vel == pytest.approx(-C.SPRING_IMPULSE_CAP_DEG_S * C.TAIL_IMPULSE_RATIO)


def test_impulse_deviation_then_settle() -> None:
    """激励后耳倾角偏离基线并振荡；12s 后收敛回与无激励模型一致（±0.01°）。"""

    excited = PetModel()
    baseline = PetModel()
    # 同步推进若干帧建立相同状态
    _run(excited, 30)
    _run(baseline, 30)

    excited.add_impulse(-20.0, 0.0)  # 拖拽一帧 20px → 耳尾甩动
    deviated = False
    for frame in range(360):  # 12s @ 30fps
        excited.update(1.0 / 30.0, float(frame))
        baseline.update(1.0 / 30.0, float(frame))
        delta_l = abs(excited.pose().ear_l_tilt - baseline.pose().ear_l_tilt)
        delta_tail = abs(excited.pose().tail_angle - baseline.pose().tail_angle)
        if delta_l > 0.5 or delta_tail > 0.5:
            deviated = True
    assert deviated, "激励后应产生可见偏离"
    assert abs(excited.pose().ear_l_tilt - baseline.pose().ear_l_tilt) < 0.01
    assert abs(excited.pose().tail_angle - baseline.pose().tail_angle) < 0.01
    assert abs(excited._ear_l_osc) < 0.5


def test_reduce_motion_ignores_impulse() -> None:
    """reduce_motion：激励被忽略、弹簧不积分（振荡恒 0）。"""

    model = PetModel()
    model.set_reduce_motion(True)
    model.add_impulse(-30.0, 10.0)
    assert model._ear_l_vel == 0.0
    _run(model, 10)
    assert model._ear_l_osc == 0.0


def test_dragging_bypasses_and_clears() -> None:
    """拖拽拎起：弹簧直通清零（拎起姿态由 dangle 通道表达，不叠加振荡）。"""

    model = PetModel()
    model.add_impulse(-20.0, 0.0)
    assert model._ear_l_vel != 0.0
    model.set_dragging(True)
    _run(model, 10)
    assert model._ear_l_osc == 0.0 and model._ear_l_vel == 0.0
    assert model._tail_osc == 0.0 and model._tail_vel == 0.0


# --------------------------------------------------------------------------- #
# 常量防漂移
# --------------------------------------------------------------------------- #
def test_spring_constants_sane() -> None:
    """弹簧常量健全性：欠阻尼、刚度为正、子步长足够小（数值稳定）。"""

    assert C.SPRING_SUB_STEP_S <= 1.0 / 120.0
    assert C.EAR_SPRING_K > 0 and C.TAIL_SPRING_K > 0
    assert 0.0 < C.EAR_SPRING_ZETA < 1.0
    assert 0.0 < C.TAIL_SPRING_ZETA < 1.0
    # 数值稳定：ω·h ≪ 2（半隐式欧拉稳定域）
    assert math.sqrt(C.EAR_SPRING_K) * C.SPRING_SUB_STEP_S < 0.5
    assert C.DRAG_IMPULSE_GAIN > 0
    assert C.SPRING_IMPULSE_CAP_DEG_S > 0
    assert 0.0 < C.TAIL_IMPULSE_RATIO <= 1.0
