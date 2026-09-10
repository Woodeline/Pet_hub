"""情绪状态机测试（PRD §5 / FR-05~FR-10）。

本文件是本套件的**核心攻击面**：精确阈值、边界值、最小驻留防抖、
敲击优先级、唤醒委屈、时间异常（倒退 / 巨大跳变）、幂等性。
"""

from __future__ import annotations

import logging

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression, Gesture, Mood
from desktop_pet.core.mood_state_machine import MoodStateMachine, expression_for_mood

_LOGGER_NAME = "desktop_pet.core.mood_state_machine"


def make_sm(now: float = 0.0) -> MoodStateMachine:
    """构造一个以 ``now`` 起始、全部使用 PRD 默认阈值的时间注入状态机。"""

    return MoodStateMachine(now=now)


# --------------------------------------------------------------------------- #
# 1. 初始态与空闲计时
# --------------------------------------------------------------------------- #
def test_initial_state_is_idle_at_t0() -> None:
    sm = make_sm(0.0)
    assert sm.mood is Mood.IDLE
    assert sm.idle_seconds(0.0) == 0.0
    assert sm.state_since() == 0.0


def test_idle_seconds_never_negative() -> None:
    sm = make_sm(0.0)
    # 传入比上次输入更早的时刻不应产生负的"无输入时长"
    assert sm.idle_seconds(-50.0) == 0.0


# --------------------------------------------------------------------------- #
# 2. 精确阈值（边界值：略小于 / 等于 / 略大于）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("t,expect_mood", [(119.99, Mood.IDLE), (120.0, Mood.REST)])
def test_idle_to_rest_boundary(t: float, expect_mood: Mood) -> None:
    """FR-08：无输入 >= 120s 进入休息；119.99s 不迁移。"""

    sm = make_sm(0.0)
    tr = sm.update(t)
    assert sm.mood is expect_mood
    assert tr.changed is (expect_mood is Mood.REST)


@pytest.mark.parametrize("t,expect_mood", [(299.99, Mood.REST), (300.0, Mood.SLEEP)])
def test_rest_to_sleep_boundary(t: float, expect_mood: Mood) -> None:
    """FR-09：无输入 >= 300s 进入睡觉；299.99s 仍为休息。"""

    sm = make_sm(0.0)
    sm.update(120.0)  # 先稳定进入 REST
    assert sm.mood is Mood.REST
    tr = sm.update(t)
    assert sm.mood is expect_mood
    assert tr.changed is (expect_mood is Mood.SLEEP)


@pytest.mark.parametrize("t,expect_mood", [(19.99, Mood.FOCUS), (20.0, Mood.IDLE)])
def test_focus_to_idle_boundary(t: float, expect_mood: Mood) -> None:
    """FR-07：停止敲击后 20s 无输入回落空闲。"""

    sm = make_sm(0.0)
    sm.on_keystroke(0.0, high_frequency=True)
    assert sm.mood is Mood.FOCUS
    tr = sm.update(t)
    assert sm.mood is expect_mood
    assert tr.changed is (expect_mood is Mood.IDLE)


# --------------------------------------------------------------------------- #
# 3. 最小驻留防抖（PRD §5：>=5s；防止阈值附近跳变）
# --------------------------------------------------------------------------- #
def test_min_dwell_blocks_then_allows_transition() -> None:
    """状态刚进入 2s 就跨过阈值 → 因驻留不足被拦住；满 5s 后才允许。"""

    sm = make_sm(0.0)
    # 手动把状态"刚"设为 IDLE（2s 前），但无输入计时器已累积到 120s
    sm.force(Mood.IDLE, 118.0)

    tr = sm.update(120.0)  # 距上次迁移仅 2s < 5s
    assert tr.changed is False
    assert sm.mood is Mood.IDLE
    assert "驻留" in tr.reason, f"应给出驻留不足的原因，实际：{tr.reason}"

    tr2 = sm.update(123.0)  # 距上次迁移 5s，恰好允许
    assert tr2.changed is True
    assert tr2.to_mood is Mood.REST


def test_min_dwell_exact_boundary_is_inclusive() -> None:
    """距上次迁移正好 5s 时应允许迁移（``>=`` 语义）。"""

    sm = make_sm(0.0)
    sm.force(Mood.IDLE, 116.0)  # 距阈值：t=120 时驻留仅 4s
    # t=120：idle 已达 120 但驻留 4s < 5s → 被拦住
    assert sm.update(120.0).changed is False
    assert "驻留" in sm.last_transition().reason
    # t=121：驻留正好 5s → 允许
    assert sm.update(121.0).changed is True
    assert sm.mood is Mood.REST


# --------------------------------------------------------------------------- #
# 4. 幂等性：同一 now 重复调用不产生二次迁移
# --------------------------------------------------------------------------- #
def test_update_idempotent_same_now() -> None:
    sm = make_sm(0.0)
    first = sm.update(120.0)
    second = sm.update(120.0)
    assert first.changed is True and first.to_mood is Mood.REST
    assert second.changed is False
    assert sm.state_since() == 120.0
    assert sm.mood is Mood.REST


def test_repeated_updates_walk_states_once() -> None:
    """按帧逐步推进不会在每个阈值处"抖动"多次。"""

    sm = make_sm(0.0)
    changes = []
    t = 0.0
    while t <= 320.0:
        tr = sm.update(t)
        if tr.changed:
            changes.append((t, tr.to_mood))
        t += 0.05
    # 只应发生 IDLE→REST→SLEEP 两次迁移
    assert [m for _, m in changes] == [Mood.REST, Mood.SLEEP]


# --------------------------------------------------------------------------- #
# 5. 敲击优先级最高（FR-10）
# --------------------------------------------------------------------------- #
def test_keystroke_resets_idle_timer() -> None:
    sm = make_sm(0.0)
    sm.on_keystroke(50.0, high_frequency=False)
    assert sm.idle_seconds(50.0) == 0.0
    assert sm.idle_seconds(60.0) == 10.0


def test_keystroke_high_frequency_enters_focus() -> None:
    sm = make_sm(0.0)
    tr = sm.on_keystroke(1.0, high_frequency=True)
    assert tr.changed is True
    assert tr.to_mood is Mood.FOCUS
    assert tr.expression is Expression.FOCUS


def test_excited_after_5s_of_sustained_high_frequency() -> None:
    """FR-12：专注态下连续高频 >=5s → 兴奋表情（仍处于 FOCUS 态）。"""

    sm = make_sm(0.0)
    sm.on_keystroke(0.0, high_frequency=True)  # 进入 FOCUS

    early = sm.on_keystroke(4.9, high_frequency=True)
    assert early.expression is Expression.FOCUS

    excited = sm.on_keystroke(5.0, high_frequency=True)
    assert excited.expression is Expression.EXCITED
    assert excited.to_mood is Mood.FOCUS  # 状态不变，仅表情升级
    assert excited.changed is False


# --------------------------------------------------------------------------- #
# 6. 睡觉唤醒 → 委屈 3s → 回落空闲（FR-09 / 补充规则）
# --------------------------------------------------------------------------- #
def test_sleep_wake_by_keystroke_gives_sulky_then_idle() -> None:
    sm = make_sm(0.0)
    sm.force(Mood.SLEEP, 300.0)

    tr = sm.on_keystroke(305.0, high_frequency=False)
    assert tr.changed is True
    assert tr.to_mood is Mood.IDLE
    assert tr.expression is Expression.SULKY
    assert sm.idle_seconds(305.0) == 0.0  # 计时器被重置

    # 委屈窗口边界：sulky_until = 305 + 3 = 308
    assert sm.sulky_active(307.999) is True
    assert sm.sulky_active(308.0) is False

    # 唤醒后不会立刻跳回睡眠/休息
    after = sm.update(306.0)
    assert after.changed is False
    assert sm.mood is Mood.IDLE


def test_sulky_not_active_when_not_woken_from_sleep() -> None:
    sm = make_sm(0.0)
    sm.on_keystroke(1.0, high_frequency=False)
    assert sm.sulky_active(2.0) is False


def test_external_wake_from_sleep() -> None:
    sm = make_sm(0.0)
    sm.force(Mood.SLEEP, 300.0)
    tr = sm.on_wake(301.0)
    assert tr.to_mood is Mood.IDLE
    assert tr.expression is Expression.SULKY
    assert sm.sulky_active(302.0) is True


def test_external_wake_when_awake_is_noop() -> None:
    sm = make_sm(0.0)
    tr = sm.on_wake(1.0)
    assert tr.changed is False


# --------------------------------------------------------------------------- #
# 7. 惊讶：长空闲后单次敲键
# --------------------------------------------------------------------------- #
def test_surprised_after_long_idle_single_keystroke() -> None:
    """FR-12：空闲 >120s 后单次敲击 → 惊讶，并回到 IDLE。"""

    sm = make_sm(0.0)
    sm.update(120.0)  # 进入 REST
    assert sm.mood is Mood.REST

    tr = sm.on_keystroke(150.0, high_frequency=False)
    assert tr.changed is True
    assert tr.to_mood is Mood.IDLE
    assert tr.expression is Expression.SURPRISED


# --------------------------------------------------------------------------- #
# 8. 异常时间输入（真实场景：笔记本合盖休眠 / 时钟跳变）
# --------------------------------------------------------------------------- #
def test_time_reversal_does_not_transition_or_crash() -> None:
    """时间倒退不应产生迁移，也不应抛异常。"""

    sm = make_sm(1000.0)
    sm.update(1200.0)  # idle=200 → REST
    assert sm.mood is Mood.REST

    back = sm.update(500.0)  # 时钟倒退
    assert back.changed is False
    assert sm.mood is Mood.REST
    assert sm.idle_seconds(500.0) == 0.0


def test_huge_time_jump_reaches_sleep() -> None:
    """系统休眠 10 小时后唤醒：idle 巨大 → 直接进入 SLEEP（终态正确）。"""

    sm = make_sm(0.0)
    tr = sm.update(36000.0)
    assert tr.changed is True
    assert tr.to_mood is Mood.SLEEP
    # 记录行为：单次 update 从 IDLE 直接跳到 SLEEP（跳过 REST 的*过程*），
    # 但终态符合 PRD §5（idle>=300 → 睡觉）。真实运行每帧调用 update，不会跳过。
    assert tr.from_mood is Mood.IDLE

    woken = sm.on_keystroke(36001.0, high_frequency=False)
    assert woken.expression is Expression.SULKY


def test_update_does_not_crash_on_nan_or_inf() -> None:
    """极端健壮性：NaN / inf 不应崩溃（记录行为）。"""

    sm = make_sm(0.0)
    try:
        sm.update(float("inf"))
        sm.update(float("nan"))
    except Exception as exc:  # noqa: BLE001
        pytest.fail(f"update 遇到 inf/nan 抛异常：{exc!r}")


# --------------------------------------------------------------------------- #
# 9. 鼠标手势
# --------------------------------------------------------------------------- #
def test_gesture_click_keeps_idle_and_happy() -> None:
    sm = make_sm(0.0)
    tr = sm.on_gesture(Gesture.CLICK, 1.0)
    assert tr.changed is False
    assert tr.expression is Expression.HAPPY


def test_gesture_click_wakes_sleep_to_sulky() -> None:
    sm = make_sm(0.0)
    sm.force(Mood.SLEEP, 300.0)
    tr = sm.on_gesture(Gesture.CLICK, 301.0)
    assert tr.to_mood is Mood.IDLE
    assert tr.expression is Expression.SULKY


def test_gesture_hover_from_rest_is_happy_not_sulky() -> None:
    sm = make_sm(0.0)
    sm.force(Mood.REST, 130.0)
    tr = sm.on_gesture(Gesture.HOVER, 131.0)
    assert tr.changed is False
    assert tr.expression is Expression.HAPPY


def test_gesture_none_is_noop() -> None:
    sm = make_sm(0.0)
    tr = sm.on_gesture(Gesture.NONE, 1.0)
    assert tr.changed is False


def test_gesture_drag_keeps_mood() -> None:
    sm = make_sm(0.0)
    tr = sm.on_gesture(Gesture.DRAG, 1.0)
    assert tr.changed is False
    assert tr.expression is Expression.HAPPY  # IDLE 的基础表情


# --------------------------------------------------------------------------- #
# 10. 可追溯日志（FR-05：状态变更日志可查）
# --------------------------------------------------------------------------- #
def test_state_change_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    sm = make_sm(0.0)
    with caplog.at_level(logging.INFO, logger=_LOGGER_NAME):
        sm.update(120.0)
    assert any("状态迁移" in msg and "REST" in msg for msg in caplog.messages)


def test_mood_to_expression_mapping() -> None:
    assert expression_for_mood(Mood.IDLE) is Expression.HAPPY
    assert expression_for_mood(Mood.FOCUS) is Expression.FOCUS
    assert expression_for_mood(Mood.REST) is Expression.SLEEPY
    assert expression_for_mood(Mood.SLEEP) is Expression.SLEEPING


# --------------------------------------------------------------------------- #
# 11. 自定义阈值注入（可测试性硬要求）
# --------------------------------------------------------------------------- #
def test_custom_thresholds_are_respected() -> None:
    sm = MoodStateMachine(idle_start_s=1.0, rest_s=2.0, sleep_s=3.0, min_dwell_s=0.0, now=0.0)
    assert sm.update(2.0).to_mood is Mood.REST
    assert sm.update(3.0).to_mood is Mood.SLEEP


def test_last_transition_reflects_latest_call() -> None:
    sm = make_sm(0.0)
    sm.on_keystroke(1.0, high_frequency=True)
    assert sm.last_transition().to_mood is Mood.FOCUS
    sm.update(100.0)
    assert sm.last_transition().to_mood is Mood.IDLE


def test_default_thresholds_match_prd_constants() -> None:
    """防漂移：状态机默认值必须等于 PRD 常量。"""

    sm = make_sm(0.0)
    assert sm._idle_start_s == C.IDLE_START_S == 20.0
    assert sm._rest_s == C.REST_THRESHOLD_S == 120.0
    assert sm._sleep_s == C.SLEEP_THRESHOLD_S == 300.0
    assert sm._min_dwell_s == C.MIN_DWELL_S == 5.0


# --------------------------------------------------------------------------- #
# 12. "敲键打断休息 → 空闲" 分支可达性（独立复核）
# --------------------------------------------------------------------------- #
def test_keystroke_interrupt_rest_branch_is_reachable() -> None:
    """REST 态下先经 CLICK 重置空闲计时器，再接单次敲键 → 命中"敲键打断休息"分支。

    （该分支位于"长空闲→惊讶"判断之后，仅当 pre_idle < 120s 时才可达；
    交互手势会重置无输入计时器，从而制造出 pre_idle < 120 的 REST 态。）
    """

    sm = make_sm(0.0)
    sm.force(Mood.REST, 120.0)  # 进入 REST（last_input 仍为 0）
    assert sm.mood is Mood.REST

    # CLICK：视为有效输入，重置无输入计时器，但情绪态保持 REST
    gesture = sm.on_gesture(Gesture.CLICK, 130.0)
    assert gesture.changed is False
    assert sm.mood is Mood.REST
    assert sm.idle_seconds(130.0) == 0.0

    # 紧接着单次敲键：pre_idle=10s < 120s → 不触发惊讶，命中"打断休息"分支
    tr = sm.on_keystroke(140.0, high_frequency=False)
    assert tr.changed is True
    assert tr.to_mood is Mood.IDLE
    assert "打断休息" in tr.reason, f"未命中打断休息分支，reason={tr.reason}"


def test_keystroke_from_rest_without_reset_gives_surprised() -> None:
    """对照：REST 态若未被交互重置（pre_idle≥120），单次敲键走的是"惊讶"分支。"""

    sm = make_sm(0.0)
    sm.force(Mood.REST, 120.0)
    tr = sm.on_keystroke(150.0, high_frequency=False)  # pre_idle=150 ≥ 120
    assert tr.to_mood is Mood.IDLE
    assert tr.expression is Expression.SURPRISED
    assert "惊讶" in tr.reason
