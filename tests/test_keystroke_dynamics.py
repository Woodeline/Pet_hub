"""敲击动力学回归测试 —— 守护 ``PetModel._apply_keystroke`` 的绝对赋值机制。

背景（本轮返修的核心架构性改动）：左右分工为「**活动侧落指、非活动侧抬腕**」——
``PetModel._apply_keystroke`` 在 ``self._current = self._current.lerp_to(target, t)``
**之后**，对**活动侧**做落指/屈指（``arm_*_press`` / ``finger_*_curl``）、对
**非活动侧**做抬腕（``arm_*_lift``）的**绝对赋值**，从而绕过全局姿态平滑
``POSE_SMOOTH_K=9``（每帧只靠拢 ~26%，会把瞬时脉冲幅度吃掉 3/4）。

把抬腕交给非活动侧有两个好处：

* 抬腕与落指**不在同一只手** → 9px 下压不会被 13.5px 上提抵消（幅度保全）；
* 抬腕在「落指阶段」即升到位 → **高频连打（间隔 < ``PRESS_DOWN_S``）也看得到抬腕**。

该机制绕过了平滑，最容易藏 bug。本文件把它固化为**永久回归**，覆盖：

* 姿态残留 / 收敛（敲击结束后通道是否回到 0，会不会卡在按压位）；
* 左右分工（活动侧落指、非活动侧抬腕，落指/屈指零串扰）；
* 高频连打（10 次/秒 × 3 秒）不漂移、无 NaN/inf、始终落在 [0,1]；
* **高频抬腕可见性**（4/6/8/10 次每秒均 ≥ 4px，治愈旧 bug）；
* 打断语义（半程再次 ``press_arm`` 必须立刻重启而非排队）；
* 与拖拽 / 睡觉的交互（拖拽期间 ``arm_dangle>0.9`` ⇒ ``arm_*_press<0.1``）；
* 单帧突变量化（视觉闪烁判据）与包络单调性；
* 时间常量在 30fps 下的帧数覆盖与 FR-02 首帧响应。

.. note::
   本文件**只读** :mod:`desktop_pet.core.pet_model`，不 import 任何 Qt。
"""

from __future__ import annotations

import math

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel

_FPS = 30.0
_DT = 1.0 / _FPS

#: 敲击瞬时通道（绝对赋值的全部目标）
_HAND_CHANNELS = (
    "arm_l_press", "arm_r_press",
    "arm_l_lift", "arm_r_lift",
    "finger_l_curl", "finger_r_curl",
)


def _snap(model: PetModel) -> dict[str, float]:
    pose = model.pose()
    return {name: getattr(pose, name) for name in _HAND_CHANNELS}


def _advance(model: PetModel, seconds: float, t0: float = 0.0) -> float:
    """按 30fps 推进 ``seconds`` 秒，返回结束时刻。"""

    t = t0
    for _ in range(int(round(seconds * _FPS))):
        t += _DT
        model.update(_DT, t)
    return t


# --------------------------------------------------------------------------- #
# A1. 姿态残留 / 卡死
# --------------------------------------------------------------------------- #
def test_arm_channels_settle_to_zero_after_single_keystroke() -> None:
    """敲击结束后，全部手臂通道必须收敛回 ~0（不得卡在按压位）。"""

    model = PetModel()
    model.press_arm()
    _advance(model, 0.4)          # 越过 PRESS_ANIM_S(0.32)，进入衰减
    _advance(model, 1.5)          # 留足衰减时间（e^{-k·dt} 指数收敛）
    settled = _snap(model)
    for name, value in settled.items():
        assert abs(value) < 1e-4, f"{name} 未收敛（={value}）"


def test_arm_channels_no_residue_after_10s_idle(capsys) -> None:
    """连续推进 10 秒（不触发新敲击）后，残留必须为机器精度量级。"""

    model = PetModel()
    model.press_arm()
    t = _advance(model, 0.5)
    t = _advance(model, 10.0, t)
    residual = _snap(model)
    with capsys.disabled():
        print("\n[keystroke] 10s 后残留:", {k: round(v, 9) for k, v in residual.items()})
    assert max(abs(v) for v in residual.values()) < 1e-6


def test_single_press_reaches_full_lift_and_press_peak() -> None:
    """单次孤立敲击：press/curl 打到活动侧峰值、lift 打到**非活动侧**峰值。

    本轮分工调整后，抬腕由**非活动侧**承担（活动侧落指、另一侧抬起），
    故 lift 峰值取自左右两手的较大者。
    """

    model = PetModel()
    model.press_arm()
    max_press = 0.0
    max_lift = 0.0
    max_curl = 0.0
    t = 0.0
    for _ in range(int(round(C.PRESS_ANIM_S * _FPS)) + 4):
        t += _DT
        model.update(_DT, t)
        pose = model.pose()
        max_press = max(max_press, pose.arm_r_press)      # 首敲 → 右爪落指
        max_lift = max(max_lift, pose.arm_l_lift, pose.arm_r_lift)  # 抬腕在非活动侧
        max_curl = max(max_curl, pose.finger_r_curl)
    assert max_press > 0.99, f"press 峰值不足：{max_press}"
    assert max_lift > 0.99, f"lift 峰值不足：{max_lift}"
    assert max_curl > 0.99, f"curl 峰值不足：{max_curl}"


# --------------------------------------------------------------------------- #
# A2. 左右完全独立
# --------------------------------------------------------------------------- #
def test_left_press_leaves_right_arm_unpressed() -> None:
    """左侧落指时，右侧**不发生落指/屈指**（抬腕由非活动侧承担，是有意为之）。"""

    model = PetModel()
    model.press_arm()
    model.press_arm()             # 两次 → 左手（_press_arm==0）
    model.update(_DT, 0.0)
    model.update(_DT, _DT)
    snap = _snap(model)
    assert snap["arm_l_press"] > 0.1, "左手未激活"
    # 非活动侧（右手）不得发生落指 / 屈指（正串扰）；抬腕则由非活动侧承担。
    assert snap["arm_r_press"] == 0.0, f"左侧敲击串扰到 arm_r_press={snap['arm_r_press']}"
    assert snap["finger_r_curl"] == 0.0, f"左侧敲击串扰到 finger_r_curl={snap['finger_r_curl']}"
    assert snap["arm_r_lift"] >= snap["arm_l_lift"], "抬腕应落在非活动侧（右手）"


def test_right_press_leaves_left_arm_unpressed() -> None:
    model = PetModel()
    model.press_arm()             # 单次 → 右手（_press_arm==1）
    model.update(_DT, 0.0)
    model.update(_DT, _DT)
    snap = _snap(model)
    assert snap["arm_r_press"] > 0.1, "右手未激活"
    assert snap["arm_l_press"] == 0.0, f"右侧敲击串扰到 arm_l_press={snap['arm_l_press']}"
    assert snap["finger_l_curl"] == 0.0, f"右侧敲击串扰到 finger_l_curl={snap['finger_l_curl']}"
    assert snap["arm_l_lift"] >= snap["arm_r_lift"], "抬腕应落在非活动侧（左手）"


def test_at_most_one_hand_rises_per_frame() -> None:
    """左右交替语义：任意一帧最多只有一只手在“上升”，另一只只能衰减。

    若两侧在同一帧同时上升，说明绝对赋值外泄到了非活动侧（正串扰）。
    """

    model = PetModel()
    prev = _snap(model)
    t = 0.0
    both_up = 0
    for _ in range(90):
        t += _DT
        model.update(_DT, t)
        snap = _snap(model)
        for a, b in (("arm_l_press", "arm_r_press"), ("arm_l_lift", "arm_r_lift"),
                     ("finger_l_curl", "finger_r_curl")):
            if snap[a] > prev[a] + 1e-9 and snap[b] > prev[b] + 1e-9:
                both_up += 1
        if abs(t - round(t / 0.1) * 0.1) < _DT / 2:
            model.press_arm()
        prev = snap
    assert both_up == 0, f"有 {both_up} 帧左右手同时上升（正串扰）"


# --------------------------------------------------------------------------- #
# A3. 高频连打：有界、有限、不漂移
# --------------------------------------------------------------------------- #
def test_high_frequency_10hz_for_3s_stays_bounded_and_finite(capsys) -> None:
    model = PetModel()
    t = 0.0
    nxt = 0.0
    lo = {c: math.inf for c in _HAND_CHANNELS}
    hi = {c: -math.inf for c in _HAND_CHANNELS}
    while t < 3.0:
        t += _DT
        if t >= nxt:
            model.press_arm()
            nxt += 0.1
        model.update(_DT, t)
        snap = _snap(model)
        for c in _HAND_CHANNELS:
            v = snap[c]
            assert math.isfinite(v), f"{c} 出现 NaN/inf"
            lo[c] = min(lo[c], v)
            hi[c] = max(hi[c], v)
    with capsys.disabled():
        print("\n[keystroke] 10Hz×3s 通道范围:")
        for c in _HAND_CHANNELS:
            print(f"    {c:<16} [{lo[c]:.4f}, {hi[c]:.4f}]")
    for c in _HAND_CHANNELS:
        assert lo[c] >= -1e-9, f"{c} 越界下溢 {lo[c]}"
        assert hi[c] <= 1.0 + 1e-9, f"{c} 越界上溢 {hi[c]}"


# --------------------------------------------------------------------------- #
# A4. 打断语义：立刻重启而非排队
# --------------------------------------------------------------------------- #
def test_press_arm_restarts_timer_when_interrupted_mid_animation() -> None:
    model = PetModel()
    model.press_arm()
    _advance(model, 0.17)                      # 动画进行中（剩 ~0.15s）
    assert 0.0 < model._press_timer < C.PRESS_ANIM_S
    model.press_arm()                          # 半程再次触发
    assert model._press_timer == pytest.approx(C.PRESS_ANIM_S), (
        f"打断后计时器未重启（={model._press_timer}），动画被排队而非重启"
    )


def test_press_arm_interrupt_toggles_side() -> None:
    model = PetModel()
    model.press_arm()                          # → 右
    right_arm = model._press_arm
    model.press_arm()                          # → 左
    assert model._press_arm == 1 - right_arm
    model.press_arm()                          # → 右
    assert model._press_arm == right_arm


def test_interrupt_reclaims_both_hands_in_order(capsys) -> None:
    """连续三次打断：两侧都应被驱动到过，且互不污染。"""

    model = PetModel()
    seen = {"l": 0.0, "r": 0.0}
    t = 0.0
    for i in range(3):
        model.press_arm()
        for _ in range(3):
            t += _DT
            model.update(_DT, t)
            p = model.pose()
            seen["l"] = max(seen["l"], p.arm_l_press)
            seen["r"] = max(seen["r"], p.arm_r_press)
    with capsys.disabled():
        print("\n[keystroke] 三次打断期间左右最大 press:", seen)
    assert seen["l"] > 0.0 and seen["r"] > 0.0


# --------------------------------------------------------------------------- #
# A5. 与拖拽 / 睡觉的交互
# --------------------------------------------------------------------------- #
def test_keystroke_during_drag_keeps_values_bounded(capsys) -> None:
    """拖拽（arm_dangle=1）期间敲击：不得出现「既下垂又落指」的叠加。

    需求 2 修复后：拖拽期间 ``_apply_keystroke`` 直接返回，落指通道不写入，
    因此 ``arm_dangle > 0.9`` 时必然 ``arm_*_press < 0.1``。本用例把该约束
    固化为**永久回归**（旧实现下拖拽 + 敲击会同时把两者驱动到 ~0.86）。
    """

    model = PetModel()
    model.set_dragging(True)
    _advance(model, 1.5)                       # 让 arm_dangle 收敛到 1
    assert model.pose().arm_dangle > 0.9
    model.press_arm()
    _advance(model, 0.1)
    pose = model.pose()
    with capsys.disabled():
        print("\n[keystroke] 拖拽+敲击: dangle=%.3f  press=%.3f" % (
            pose.arm_dangle, max(pose.arm_l_press, pose.arm_r_press)))
    assert 0.0 <= pose.arm_dangle <= 1.0
    assert 0.0 <= pose.arm_l_press <= 1.0
    assert 0.0 <= pose.arm_r_press <= 1.0
    # 需求 2：被拎起（dangle>0.9）时不得落指
    if pose.arm_dangle > 0.9:
        assert pose.arm_l_press < 0.1, f"拖拽时仍在落指 arm_l_press={pose.arm_l_press}"
        assert pose.arm_r_press < 0.1, f"拖拽时仍在落指 arm_r_press={pose.arm_r_press}"


def test_keystroke_under_sleeping_expression_still_drives_hand() -> None:
    model = PetModel()
    model.set_base_expression(Expression.SLEEPING)
    model.set_expression(Expression.SLEEPING, 0.0)
    _advance(model, 1.0)
    assert model._effective_expression() is Expression.SLEEPING
    model.press_arm()
    _advance(model, 0.1)
    pose = model.pose()
    assert max(pose.arm_l_press, pose.arm_r_press) > 0.1, "睡觉态下敲击未生效"


# --------------------------------------------------------------------------- #
# A6. 单帧突变量化（视觉闪烁判据）
# --------------------------------------------------------------------------- #
def test_isolated_press_max_adjacent_frame_delta_bounded(capsys) -> None:
    """单次敲击在 30fps 下相邻帧最大跳变应有界（不出现 0→1 的整体闪跳）。"""

    model = PetModel()
    model.press_arm()
    prev = _snap(model)
    max_delta = {c: 0.0 for c in _HAND_CHANNELS}
    t = 0.0
    for _ in range(int(round(C.PRESS_ANIM_S * _FPS)) + 10):
        t += _DT
        model.update(_DT, t)
        snap = _snap(model)
        for c in _HAND_CHANNELS:
            max_delta[c] = max(max_delta[c], abs(snap[c] - prev[c]))
        prev = snap
    with capsys.disabled():
        print("\n[keystroke] 单次敲击相邻帧最大跳变:")
        for c in _HAND_CHANNELS:
            print(f"    {c:<16} {max_delta[c]:.4f}")
    # 实测 ~0.56（≈5.0px）；阈值放宽到 0.60 仅用于捕捉“退化为 0→1 整体闪跳”的回归
    assert max(max_delta.values()) <= 0.60, (
        f"相邻帧跳变过大（{max(max_delta.values()):.4f}），疑似视觉闪烁"
    )


def test_single_press_envelope_is_monotone_then_monotone() -> None:
    """落指阶段单调上升、回弹阶段单调下降 —— 排除“抖动闪烁”。"""

    model = PetModel()
    model.press_arm()
    presses = []
    t = 0.0
    for _ in range(int(round(C.PRESS_ANIM_S * _FPS)) + 2):
        t += _DT
        model.update(_DT, t)
        presses.append(model.pose().arm_r_press)

    peak = presses.index(max(presses))
    up = presses[: peak + 1]
    down = presses[peak:]
    assert all(b >= a - 1e-9 for a, b in zip(up, up[1:])), f"落指阶段非单调：{up}"
    assert all(b <= a + 1e-9 for a, b in zip(down, down[1:])), f"回弹阶段非单调：{down}"


# --------------------------------------------------------------------------- #
# E. 时间常量 / FR-02
# --------------------------------------------------------------------------- #
def test_keystroke_phase_lengths_cover_minimum_frames_at_30fps() -> None:
    assert C.PRESS_DOWN_S * 30 >= 4.0, "落指阶段 < 4 帧（30fps）"
    assert C.PRESS_REBOUND_S * 30 >= 4.0, "回弹阶段 < 4 帧（30fps）"
    assert C.PRESS_ANIM_S == pytest.approx(C.PRESS_DOWN_S + C.PRESS_REBOUND_S)


@pytest.mark.parametrize("dt_ms", [33, 67, 100])
def test_fr02_first_frame_response_within_100ms(dt_ms: int) -> None:
    """按键后**首帧**即产生可见位移（FR-02：按键到首帧 < 100ms）。"""

    model = PetModel()
    model.press_arm()
    model.update(dt_ms / 1000.0, 0.0)
    pose = model.pose()
    disp_px = max(pose.arm_l_press, pose.arm_r_press) * 9.0
    assert disp_px > 1.0, f"dt={dt_ms}ms 首帧位移仅 {disp_px:.2f}px，反馈不可见"


def test_high_freq_lift_visible_across_rates(capsys) -> None:
    """回归（需求 1）：高频连打时抬腕**不得消失**。

    抬腕现由**非活动侧**承担，且在「落指阶段」即升到位，因此即便敲击间隔
    < ``PRESS_DOWN_S``（8/s=0.125s、10/s=0.1s ≥ ``PRESS_DOWN_S`` 的 0.14s）时，
    抬腕依然升起。验收：``max(arm_l_lift, arm_r_lift) * 13.5px`` 在
    4 / 6 / 8 / 10 次每秒四档均 ≥ 4px。

    .. note::
       本用例替代旧的「抬腕在高频下恒为 0」特征化用例——那正是本轮要修的 bug。
    """

    table = []
    for rate in (4, 6, 8, 10):
        model = PetModel()
        t = 0.0
        nxt = 0.0
        max_lift = 0.0
        while t < 1.2:
            t += _DT
            if t >= nxt:
                model.press_arm()
                nxt += 1.0 / rate
            model.update(_DT, t)
            p = model.pose()
            max_lift = max(max_lift, p.arm_l_lift, p.arm_r_lift)
        table.append((rate, max_lift))
    with capsys.disabled():
        print("\n[keystroke] 抬腕峰值 vs 敲击速率:")
        for rate, lift in table:
            print(f"    {rate:>2}/s -> max_lift={lift:.3f} ({lift * 13.5:.1f}px)")

    by_rate = dict(table)
    for rate in (4, 6, 8, 10):
        disp_px = by_rate[rate] * 13.5
        assert disp_px >= 4.0, f"{rate}/s 时抬腕仅 {disp_px:.2f}px（< 4px 不可见）"
