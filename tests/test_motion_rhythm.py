"""动效节奏去机械化测试（阶段 A5：呼吸相位随机化 + SurpriseKind 小动作 + 不对称眨眼）。

依据权威方案 ``docs/design-ui-fatigue-plan-v1.1.md`` §3 A5。

全部为 ``core`` **纯逻辑**测试，不需要 Qt。呼吸随机化走 ``PetModel`` 内部 ``random.Random``，
测试以 ``model._rng = random.Random(seed)`` 注入固定种子做可复现验证。
"""

from __future__ import annotations

import math
import random
from dataclasses import fields

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel, PetPose, SurpriseKind

_TWO_PI = 2.0 * math.pi


# --------------------------------------------------------------------------- #
# 0. FR-34 回归守卫 —— A5 不得污染「恒定时钟帧率无关」
# --------------------------------------------------------------------------- #
def _frozen_clock_pose(fps: int, seconds: float, expr: Expression) -> PetPose:
    """在 ``now`` 冻结（目标姿态恒定）下跑 ``seconds`` 秒，返回末帧姿态。"""

    model = PetModel()
    model.set_base_expression(expr)
    model.set_expression(expr, 0.0)  # 清空临时表情，避免插队干扰
    dt = 1.0 / fps
    for _ in range(int(round(fps * seconds))):
        model.update(dt, 1.0)  # now 冻结
    return model.pose()


def test_frozen_clock_frame_rate_independence_regression() -> None:
    """``now`` 冻结（目标姿态恒定）时，30fps 与 60fps 结果必须**精确一致**（FR-34 核心承诺）。

    这是 A5 的回归守卫：呼吸改为 epoch 锚定相位后，``now`` 冻结 ⇒ 相位恒定 ⇒ 目标恒定，
    逐帧指数平滑仍帧率无关。若呼吸回退成「dt 累加」型实现，此断言立即失败。
    """

    p30 = _frozen_clock_pose(30, 1.0, Expression.SURPRISED)
    p60 = _frozen_clock_pose(60, 1.0, Expression.SURPRISED)
    worst = max(abs(getattr(p30, f.name) - getattr(p60, f.name)) for f in fields(PetPose))
    assert worst < 1e-6, f"恒定时钟帧率无关性被破坏（最大通道差 {worst}）"


# --------------------------------------------------------------------------- #
# 1. 呼吸：纯函数形态 + epoch 锚定相位
# --------------------------------------------------------------------------- #
def test_breath_offset_phased_literal_values() -> None:
    """``breath_offset_phased`` = ``amplitude · sin(2π·phase)``（字面量端点/极值）。"""

    assert motion.breath_offset_phased(0.0, 1.0) == 0.0
    assert motion.breath_offset_phased(0.25, 1.0) == pytest.approx(1.0)
    assert motion.breath_offset_phased(0.5, 1.0) == pytest.approx(0.0)
    assert motion.breath_offset_phased(0.75, 1.0) == pytest.approx(-1.0)


def test_breath_offset_phased_scales_with_amplitude() -> None:
    assert motion.breath_offset_phased(0.25, 3.5) == pytest.approx(3.5)
    assert motion.breath_offset_phased(0.75, 3.5) == pytest.approx(-3.5)
    assert motion.breath_offset_phased(0.0, 3.5) == 0.0


def test_breath_offset_legacy_is_stateless_and_unchanged() -> None:
    """``breath_offset`` 保留原签名与**无状态**行为（其它调用方不动）。"""

    for now in (0.0, 0.75, 3.0, 7.25):
        expected = C.BREATH_AMPLITUDE_PX * math.sin(
            _TWO_PI * ((now / C.BREATH_PERIOD_S) % 1.0)
        )
        assert motion.breath_offset(now) == pytest.approx(expected)
    # 半周期处与整周期处均为 0 点（无状态相位，与调用历史无关）
    assert motion.breath_offset(1.5, 3.0) == pytest.approx(0.0, abs=1e-9)
    assert motion.breath_offset(3.0, 3.0) == pytest.approx(0.0, abs=1e-9)


@pytest.mark.parametrize("now", [0.0, 1.5, 10.0, 123.75])
def test_first_frame_phase_matches_legacy_cycle_phase(now: float) -> None:
    """首帧相位 == 旧 ``cycle_phase(now, period)``（保持既有首帧语义）。"""

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)
    model.update(0.0, now)  # dt=0 → 不推进计时，只求首帧相位
    assert model._breath_phase == pytest.approx(motion.cycle_phase(now, C.BREATH_PERIOD_S))


def test_breath_phase_frozen_when_clock_frozen() -> None:
    """``now`` 冻结 ⇒ 相位恒定（FR-34 的根因保证）。"""

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)
    seen = set()
    for _ in range(200):
        model.update(0.033, 2.5)
        seen.add(round(model._breath_phase, 12))
    assert len(seen) == 1, f"冻结时钟下相位不恒定：{sorted(seen)[:5]} …"


def test_breath_advances_when_clock_advances() -> None:
    """``now`` 推进 ⇒ 相位严格推进且逐帧不重复。"""

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)
    dt = 1.0 / 30.0
    now = 0.0
    phases: list[float] = []
    for _ in range(45):  # 1.5s ≈ 半周期
        now += dt
        model.update(dt, now)
        phases.append(model._breath_phase)
    assert phases[-1] > phases[0]
    assert len({round(p, 9) for p in phases}) == len(phases)


def test_breath_phase_continuous_across_period_wrap() -> None:
    """周期回绕点相位连续：**回绕帧的位移增量不得大于普通帧的增量**（R2 根治点）。

    旧实现（周期中途变更 → 相位瞬跳）会在回绕处产生远大于单帧步长的位移尖峰；
    epoch 锚定后周期只在回绕点（相位 ≈ 0/1、``sin`` ≈ 0）变更 → 值与导数连续。
    """

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)

    dt = 1.0 / 30.0
    now = 0.0
    phases: list[float] = []
    for _ in range(1200):  # 40s → 跨越多轮呼吸周期
        now += dt
        model.update(dt, now)
        phases.append(model._breath_phase)

    offsets = [motion.breath_offset_phased(p, C.BREATH_AMPLITUDE_PX) for p in phases]
    deltas = [abs(offsets[i] - offsets[i - 1]) for i in range(1, len(offsets))]

    # 回绕帧 = 相位较上一帧"回退"（否则相位单调递增）
    wraps = [i for i in range(1, len(phases)) if phases[i] < phases[i - 1]]
    assert wraps, "40s 内应至少发生一次呼吸周期回绕"

    plain = [deltas[i - 1] for i in range(1, len(offsets)) if i not in wraps]
    across = [deltas[i - 1] for i in wraps]
    assert max(across) <= max(plain) * 1.5, (
        f"回绕帧位移增量 {max(across):.4f} 明显大于普通帧 {max(plain):.4f} —— 相位不连续"
    )

    # 另加绝对上界：任何相邻帧位移增量都不超过"单帧最大增量"（按最短抖动周期估算）
    single_frame_max = (
        C.BREATH_AMPLITUDE_PX * _TWO_PI * dt
        / (C.BREATH_PERIOD_S * (1.0 - C.BREATH_JITTER))
    )
    assert max(deltas) <= single_frame_max * 1.05


def test_breath_resampled_period_within_jitter_band() -> None:
    """每轮回绕重抽的周期必须落在 ``3.0 ±10%`` 闭区间（即字面量 ``[2.7, 3.3]``）。"""

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)

    dt = 1.0 / 30.0
    now = 0.0
    prev = model._breath_period
    resampled: list[float] = []
    for _ in range(1500):  # 50s → 约 16 轮
        now += dt
        model.update(dt, now)
        if model._breath_period != prev:
            resampled.append(model._breath_period)
            prev = model._breath_period

    assert resampled, "应至少发生一次呼吸周期重抽"
    out_of_band = [p for p in resampled if not (2.7 <= p <= 3.3)]
    assert not out_of_band, f"越界周期：{out_of_band}"
    assert len({round(p, 6) for p in resampled}) > 1, "周期从未变化（抖动失效）"


def test_breath_randomization_reproducible_with_fixed_seed() -> None:
    """固定种子 ⇒ 呼吸相位/周期轨迹逐帧可复现。"""

    def trace() -> list[tuple[float, float]]:
        model = PetModel()
        model._rng = random.Random(20240919)
        # 隔离呼吸：冻结眨眼 / 小动作计时器，使唯一消耗 rng 的路径只剩呼吸周期重抽，
        # 否则 ``__init__`` 里未播种的初始眨眼间隔会让两实例的 rng 流错位。
        model._blink_timer = 1.0e9
        model._surprise_timer = 1.0e9
        model.set_base_expression(Expression.HAPPY)
        model.set_expression(Expression.HAPPY, 0.0)
        dt = 1.0 / 30.0
        now = 0.0
        out: list[tuple[float, float]] = []
        for _ in range(1200):
            now += dt
            model.update(dt, now)
            out.append((round(model._breath_phase, 12), round(model._breath_period, 12)))
        return out

    assert trace() == trace()


# --------------------------------------------------------------------------- #
# 2. 偶发小动作包络（surprise_envelope）
# --------------------------------------------------------------------------- #
def test_surprise_envelope_endpoint_literals() -> None:
    """端点严格：``elapsed<=0 → 0.0``、``elapsed>=duration → 0.0``、``duration<=0 → 0.0``。"""

    assert motion.surprise_envelope(0.0, 1.2) == 0.0
    assert motion.surprise_envelope(-0.5, 1.2) == 0.0
    assert motion.surprise_envelope(1.2, 1.2) == 0.0
    assert motion.surprise_envelope(5.0, 1.2) == 0.0
    assert motion.surprise_envelope(0.5, 0.0) == 0.0


def test_surprise_envelope_has_unit_hold_plateau() -> None:
    """保持段（``0.3d ~ 0.6d``，d=1.2 → ``0.36 ~ 0.72``）包络恒为 1.0。"""

    assert motion.surprise_envelope(0.36, 1.2) == pytest.approx(1.0)
    assert motion.surprise_envelope(0.5, 1.2) == 1.0
    assert motion.surprise_envelope(0.72 - 1e-9, 1.2) == pytest.approx(1.0)


def test_surprise_envelope_attack_and_release_are_monotone() -> None:
    up = [motion.surprise_envelope(t, 1.2) for t in (0.06, 0.18, 0.30)]
    assert all(0.0 < v < 1.0 for v in up)
    assert up == sorted(up)

    down = [motion.surprise_envelope(t, 1.2) for t in (0.80, 0.95, 1.10)]
    assert all(0.0 < v < 1.0 for v in down)
    assert down == sorted(down, reverse=True)


# --------------------------------------------------------------------------- #
# 3. SurpriseKind 独立性 + 增量表合法通道（R4 守卫）
# --------------------------------------------------------------------------- #
def test_surprise_kind_is_independent_from_expression() -> None:
    """``SurpriseKind`` 独立于 ``Expression``；``Expression`` 成员数锁死为 8（R4）。

    阶段 C1-2 新增两个「换姿态」成员（``LOAF`` / ``LIE_SIDE``）——本断言仍保持**全等**
    强约束（只是集合随之扩大），并继续保证与 ``Expression`` 名字**互不相交**。
    """

    assert not issubclass(SurpriseKind, Expression)
    # 2026-09-29 增补分段小表演成员（FAKE_SLEEP / HICCUP，见 SURPRISE_SEQUENCES）
    assert {k.name for k in SurpriseKind} == {
        "STRETCH", "TAIL_FLICK", "EAR_FLICK", "GLANCE_CORNER",
        "LOAF", "LIE_SIDE", "FAKE_SLEEP", "HICCUP",
    }
    assert len(list(Expression)) == 9  # 2026-09-29 增补 TIRED
    expression_names = {e.name for e in Expression}
    assert not ({k.name for k in SurpriseKind} & expression_names)


def test_surprise_poses_only_use_existing_channels() -> None:
    """``SURPRISE_POSES`` 只用既有姿态通道（G3：不得引入新通道）。"""

    valid_channels = {f.name for f in fields(PetPose)}
    kind_names = {k.name for k in SurpriseKind}

    # 分段小表演（SURPRISE_SEQUENCES）与静态增量（SURPRISE_POSES）两表并起来
    # 必须恰好覆盖全部成员（2026-09-29 起 FAKE_SLEEP / HICCUP 只在 SEQUENCES）
    assert set(C.SURPRISE_POSES) | set(C.SURPRISE_SEQUENCES) == kind_names
    assert not (set(C.SURPRISE_POSES) & set(C.SURPRISE_SEQUENCES)), (
        "同一成员不得同时出现在静态增量表与分段表演表"
    )
    for kind_name, deltas in C.SURPRISE_POSES.items():
        assert deltas, f"{kind_name} 增量为空"
        extra = set(deltas) - valid_channels
        assert not extra, f"{kind_name} 使用了不存在的通道：{extra}"
    for kind_name, segments in C.SURPRISE_SEQUENCES.items():
        assert segments, f"{kind_name} 分段为空"
        assert segments[0][0] == 0.0, f"{kind_name} 首段必须从进度 0 开始"
        for seg_start, seg_deltas in segments:
            assert 0.0 <= seg_start <= 1.0, f"{kind_name} 段起点越界：{seg_start}"
            extra = set(seg_deltas) - valid_channels
            assert not extra, f"{kind_name} 使用了不存在的通道：{extra}"
        assert C.SURPRISE_SEQUENCE_DURATIONS.get(kind_name), (
            f"{kind_name} 缺少 SURPRISE_SEQUENCE_DURATIONS 时长"
        )


# --------------------------------------------------------------------------- #
# 4. 小动作调度门控（G3：四种抑制条件 + 空闲阈值复用）
# --------------------------------------------------------------------------- #
def _happy_model() -> PetModel:
    """构造一个基础表情为 HAPPY（= IDLE 对应态）的模型。"""

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)
    return model


def _arm_surprise(model: PetModel) -> None:
    """把模型推过空闲阈值、并把触发倒计时清零（令下一次 update 必触发，若门控放行）。"""

    model._calm_seconds = C.REST_THRESHOLD_S
    model._surprise_timer = 0.0


def test_surprise_triggers_in_idle_when_all_gates_open() -> None:
    model = _happy_model()
    _arm_surprise(model)
    model.update(0.033, 1.0)
    assert model._surprise_kind is not None, "门控全开时小动作应触发"


def test_surprise_waits_for_rest_threshold() -> None:
    """平静时长未达 ``REST_THRESHOLD_S`` 前不触发（复用同一空闲阈值，G3）。"""

    model = _happy_model()
    model._surprise_timer = 0.0
    model._calm_seconds = C.REST_THRESHOLD_S - 1.0
    model.update(0.033, 1.0)
    assert model._surprise_kind is None


def test_surprise_suppressed_while_sleeping() -> None:
    model = PetModel()
    model.set_base_expression(Expression.SLEEPING)
    model.set_expression(Expression.SLEEPING, 0.0)
    _arm_surprise(model)
    model.update(0.033, 1.0)
    assert model._surprise_kind is None, "SLEEPING 下不应触发小动作"


def test_surprise_suppressed_while_dragging() -> None:
    model = _happy_model()
    model.set_dragging(True)
    _arm_surprise(model)
    model.update(0.033, 1.0)
    assert model._surprise_kind is None, "拖拽中不应触发小动作"


def test_surprise_suppressed_during_temp_expression() -> None:
    model = _happy_model()
    model.set_expression(Expression.SURPRISED, 10.0)  # 临时表情长期存在
    _arm_surprise(model)
    model.update(0.033, 1.0)
    assert model._surprise_kind is None, "存在临时表情时不应触发小动作"


def test_surprise_suppressed_when_reduce_motion_enabled() -> None:
    model = _happy_model()
    model.set_reduce_motion(True)
    _arm_surprise(model)
    model.update(0.033, 1.0)
    assert model._surprise_kind is None, "reduce_motion 开启时不应触发小动作"


def test_reduce_motion_does_not_stop_breathing() -> None:
    """``reduce_motion`` 只抑制小动作，不冻结常态生命体征（呼吸照旧）。"""

    model = _happy_model()
    model.set_reduce_motion(True)
    dt = 1.0 / 30.0
    now = 0.0
    phases: list[float] = []
    for _ in range(45):
        now += dt
        model.update(dt, now)
        phases.append(model._breath_phase)
    assert len({round(p, 9) for p in phases}) > 1


def test_active_surprise_applies_pose_delta_then_expires() -> None:
    """小动作进行中按包络把增量叠加到目标姿态；结束后通道归位。"""

    model = _happy_model()
    base = PetModel.pose_for_expression(Expression.HAPPY)

    # 保持段（包络 = 1.0）：STRETCH 的 body_y 增量应完整叠加
    model._surprise_kind = SurpriseKind.STRETCH
    model._surprise_elapsed = C.SURPRISE_DURATION_S * 0.45
    stretched = PetModel.pose_for_expression(Expression.HAPPY)
    model._apply_actions(stretched)
    delta = C.SURPRISE_POSES[SurpriseKind.STRETCH.name]["body_y"]
    assert stretched.body_y == pytest.approx(base.body_y + delta)
    assert stretched.body_y < base.body_y  # STRETCH 为身体上提（负位移）

    # 无进行中的小动作 ⇒ 通道不受影响
    model._surprise_kind = None
    resting = PetModel.pose_for_expression(Expression.HAPPY)
    model._apply_actions(resting)
    assert resting.body_y == pytest.approx(base.body_y)


# --------------------------------------------------------------------------- #
# 5. 不对称眨眼（P3：只影响右眼）
# --------------------------------------------------------------------------- #
def test_blink_delay_affects_only_right_eye() -> None:
    """右眼比左眼晚 ``BLINK_EYE_DELAY_S`` 起闭（``blink_curve`` 本身不动）。"""

    model = PetModel()
    base = PetModel.pose_for_expression(Expression.FOCUS)
    base_l, base_r = base.eye_open_l, base.eye_open_r  # FOCUS：1.0 / 1.0

    # 相位落在 [0, BLINK_EYE_DELAY_S) 内：左眼已开始闭合，右眼仍全开（延迟生效）
    model._blinking = True
    model._blink_elapsed = C.BLINK_EYE_DELAY_S / 2.0  # 0.025
    early = PetModel.pose_for_expression(Expression.FOCUS)
    model._apply_life_signs(early, 10.0)
    assert early.eye_open_l < base_l
    assert early.eye_open_r == pytest.approx(base_r)
    # 左眼闭合进程 = blink_curve(0.025, 0.15) = |2·(0.025/0.15) − 1| = 2/3
    assert early.eye_open_l == pytest.approx(
        base_l * abs(2.0 * 0.025 / C.BLINK_DURATION_S - 1.0)
    )


def test_blink_delay_makes_right_eye_lag_behind_left() -> None:
    """延迟后段：右眼比左眼更"滞后"（闭合程度不同 ⇒ 不对称）。"""

    model = PetModel()
    model._blinking = True
    model._blink_elapsed = C.BLINK_EYE_DELAY_S + C.BLINK_DURATION_S / 2.0  # 0.125
    pose = PetModel.pose_for_expression(Expression.FOCUS)
    model._apply_life_signs(pose, 10.0)
    # 左：blink_curve(0.125) = |2·(0.125/0.15) − 1| = 2/3；右：blink_curve(0.075) = 0.0（完全闭合）
    assert pose.eye_open_l == pytest.approx(
        1.0 * abs(2.0 * 0.125 / C.BLINK_DURATION_S - 1.0)
    )
    assert pose.eye_open_r == pytest.approx(0.0)
    assert pose.eye_open_r < pose.eye_open_l


def test_blink_delay_is_less_than_half_duration() -> None:
    """延迟必须 < ``BLINK_DURATION_S/2``，否则两眼会跨过弧线眼阈值（方案 A5-3 注意）。"""

    assert C.BLINK_EYE_DELAY_S < C.BLINK_DURATION_S / 2.0
