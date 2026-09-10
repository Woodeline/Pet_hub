"""core.mood_state_machine —— 四态情绪状态机（PRD §5 / FR-05~FR-10）。

**本模块禁止 import 任何图形界面（Qt/GUI）库。**

关键约定：
- 时间一律由调用方以 ``float`` 秒（``time.monotonic()``）注入，
  **状态机内部绝不调用 ``time``**（可测试性硬要求）。
- 状态：``IDLE / FOCUS / REST / SLEEP``；最小驻留 ``MIN_DWELL_S=5s`` 防抖。
- 优先级：敲击反馈（输入驱动）> 交互反馈 > 常态自动迁移。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Final, Optional

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression, Gesture, Mood

logger = logging.getLogger(__name__)

#: 情绪态 → 建议基础表情映射
_STATE_EXPRESSION: Final[dict[Mood, Expression]] = {
    Mood.IDLE: Expression.HAPPY,
    Mood.FOCUS: Expression.FOCUS,
    Mood.REST: Expression.SLEEPY,
    Mood.SLEEP: Expression.SLEEPING,
}


def expression_for_mood(mood: Mood) -> Expression:
    """返回某情绪态对应的**基础表情**（供模型设置常态表情使用）。"""

    return _STATE_EXPRESSION.get(mood, Expression.HAPPY)


@dataclass
class MoodTransition:
    """一次状态机推进的结果描述。

    Attributes:
        from_mood: 迁移前状态。
        to_mood: 迁移后状态。
        expression: 建议的表情（供模型/控制器使用）。
        reason: 可追溯的迁移原因（写入日志）。
        timestamp: 迁移发生的时刻（秒）。
        changed: 情绪态是否**实际发生变化**。
    """

    from_mood: Mood
    to_mood: Mood
    expression: Expression
    reason: str
    timestamp: float
    changed: bool


class MoodStateMachine:
    """四态情绪状态机。

    状态迁移规则（PRD §5）：
    - 无输入 >= ``idle_start_s``(20s)：中间态 ``IDLE``。
    - 高频敲击：进入 ``FOCUS``；停止敲击后 20s 无输入回落 ``IDLE``。
    - 无输入 >= ``rest_s``(120s)：``REST``。
    - 无输入 >= ``sleep_s``(300s)：``SLEEP``。
    - 任意敲键 / 点击：重置无输入计时器；``SLEEP`` 被唤醒后 ``WAKE_SULKY_S`` 内建议 SULKY。
    - 状态切换受最小驻留 ``min_dwell_s`` 防抖约束（输入驱动迁移除外）。
    """

    def __init__(
        self,
        idle_start_s: float = C.IDLE_START_S,
        rest_s: float = C.REST_THRESHOLD_S,
        sleep_s: float = C.SLEEP_THRESHOLD_S,
        min_dwell_s: float = C.MIN_DWELL_S,
        now: float = 0.0,
    ) -> None:
        """构造状态机。

        Args:
            idle_start_s: 空闲态起始阈值（秒）。
            rest_s: 休息态阈值（秒）。
            sleep_s: 睡觉态阈值（秒）。
            min_dwell_s: 最小驻留时长（秒），防抖。
            now: 初始时刻（秒），默认 0.0（便于测试注入）。
        """

        self._idle_start_s: float = float(idle_start_s)
        self._rest_s: float = float(rest_s)
        self._sleep_s: float = float(sleep_s)
        self._min_dwell_s: float = float(min_dwell_s)

        self._state: Mood = Mood.IDLE
        self._state_since: float = float(now)
        self._last_input_ts: float = float(now)

        # 专注态下"连续高频"累计起点；非专注时为 None
        self._high_freq_since: Optional[float] = None
        # 睡觉唤醒后的"委屈"截止时刻
        self._sulky_until: float = float("-inf")
        # 情绪态已连续保持时长（用于休息态持续时间判断）
        self._last_transition: MoodTransition = MoodTransition(
            from_mood=Mood.IDLE,
            to_mood=Mood.IDLE,
            expression=_STATE_EXPRESSION[Mood.IDLE],
            reason="初始化",
            timestamp=float(now),
            changed=False,
        )

    # ------------------------------------------------------------------ #
    # 只读属性
    # ------------------------------------------------------------------ #
    @property
    def mood(self) -> Mood:
        """当前情绪态。"""

        return self._state

    def state_since(self) -> float:
        """返回当前状态进入时刻（秒）。"""

        return self._state_since

    def idle_seconds(self, now: float) -> float:
        """返回自最近一次有效输入以来的秒数（不小于 0）。"""

        return max(0.0, float(now) - self._last_input_ts)

    def last_transition(self) -> MoodTransition:
        """返回最近一次推进产生的迁移描述。"""

        return self._last_transition

    def sulky_active(self, now: float) -> bool:
        """返回当前是否处于"睡觉被唤醒后的委屈窗口"内。"""

        return float(now) < self._sulky_until

    # ------------------------------------------------------------------ #
    # 自动推进
    # ------------------------------------------------------------------ #
    def update(self, now: float) -> MoodTransition:
        """按无输入时长自动推进状态（由帧循环调用）。

        Args:
            now: 当前时刻（秒）。

        Returns:
            :class:`MoodTransition`（``changed=False`` 表示无迁移）。
        """

        now = float(now)
        idle = self.idle_seconds(now)

        # 优先级：SLEEP > REST > (FOCUS 回落 IDLE)
        if idle >= self._sleep_s and self._state != Mood.SLEEP:
            if self._can_transition(now):
                return self._emit(self._set_state(
                    Mood.SLEEP, now, f"无输入 {idle:.1f}s ≥ {self._sleep_s:.0f}s → 睡觉"
                ))
            return self._emit(self._no_change(now, f"等待驻留满足后进入睡觉（idle={idle:.1f}s）"))

        if idle >= self._rest_s and self._state not in (Mood.REST, Mood.SLEEP):
            if self._can_transition(now):
                return self._emit(self._set_state(
                    Mood.REST, now, f"无输入 {idle:.1f}s ≥ {self._rest_s:.0f}s → 休息"
                ))
            return self._emit(self._no_change(now, f"等待驻留满足后进入休息（idle={idle:.1f}s）"))

        if self._state == Mood.FOCUS and idle >= self._idle_start_s:
            if self._can_transition(now):
                return self._emit(self._set_state(
                    Mood.IDLE, now, f"停止敲击 {idle:.1f}s ≥ {self._idle_start_s:.0f}s → 空闲"
                ))
            return self._emit(self._no_change(now, "专注→空闲：等待驻留满足"))

        return self._emit(self._no_change(now, "保持当前状态"))

    # ------------------------------------------------------------------ #
    # 输入驱动迁移
    # ------------------------------------------------------------------ #
    def on_keystroke(self, now: float, high_frequency: bool) -> MoodTransition:
        """处理一次敲键事件（重置无输入计时器 / 可能进入专注 / 唤醒睡觉）。

        Args:
            now: 当前时刻（秒）。
            high_frequency: 是否由聚合器判定为高频敲击。

        Returns:
            :class:`MoodTransition`。
        """

        now = float(now)
        pre_idle = self.idle_seconds(now)
        was_sleeping = self._state == Mood.SLEEP

        # 任意有效敲键都重置"无输入计时器"（PRD 补充规则）
        self._last_input_ts = now

        # 1) 睡觉被唤醒 → 委屈 → 空闲
        if was_sleeping:
            self._sulky_until = now + C.WAKE_SULKY_S
            return self._emit(self._set_state(
                Mood.IDLE, now, "睡觉中被敲键唤醒 → 委屈 3s → 空闲",
                expression=Expression.SULKY,
            ))

        # 2) 高频敲击
        if high_frequency:
            if self._state == Mood.FOCUS:
                if self._high_freq_since is None:
                    self._high_freq_since = now
                elapsed = now - self._high_freq_since
                if elapsed >= C.EXCITED_THRESHOLD_S:
                    return self._emit(self._no_change(
                        now, f"专注态连续高频 {elapsed:.1f}s ≥ {C.EXCITED_THRESHOLD_S:.0f}s → 兴奋",
                        expression=Expression.EXCITED,
                    ))
                return self._emit(self._no_change(now, "专注保持", expression=Expression.FOCUS))
            # 进入专注（输入驱动，优先级最高，不受驻留约束）
            self._high_freq_since = now
            return self._emit(self._set_state(
                Mood.FOCUS, now, "高频敲击 → 专注",
                expression=Expression.FOCUS,
            ))

        # 3) 非高频单次敲键
        self._high_freq_since = None
        if pre_idle >= C.SURPRISED_IDLE_S:
            return self._emit(self._set_state(
                Mood.IDLE, now, f"长时间空闲 {pre_idle:.1f}s 后单次敲键 → 惊讶",
                expression=Expression.SURPRISED,
            ))
        if self._state in (Mood.REST, Mood.SLEEP):
            return self._emit(self._set_state(
                Mood.IDLE, now, "敲键打断休息 → 空闲",
            ))
        if self._state == Mood.FOCUS:
            return self._emit(self._no_change(now, "专注保持", expression=Expression.FOCUS))
        return self._emit(self._no_change(now, "敲击反馈", expression=Expression.HAPPY))

    def on_wake(self, now: float) -> MoodTransition:
        """外部显式唤醒（托盘/双击等）。

        Args:
            now: 当前时刻（秒）。
        """

        now = float(now)
        pre = self._state
        self._last_input_ts = now
        if pre == Mood.SLEEP:
            self._sulky_until = now + C.WAKE_SULKY_S
            return self._emit(self._set_state(
                Mood.IDLE, now, "外部唤醒 → 委屈 3s → 空闲",
                expression=Expression.SULKY,
            ))
        return self._emit(self._no_change(now, "唤醒请求（非睡觉态）"))

    def on_gesture(self, gesture: Gesture, now: float) -> MoodTransition:
        """处理鼠标手势（点击 / 悬停 / 拖拽 / 唤醒）。

        Args:
            now: 当前时刻（秒）。
            gesture: 手势类型。

        Returns:
            :class:`MoodTransition`。
        """

        now = float(now)
        pre = self._state

        if gesture == Gesture.NONE:
            return self._emit(self._no_change(now, "无手势"))

        # 任意交互都视为"有效输入"，重置无输入计时器
        self._last_input_ts = now

        if pre == Mood.SLEEP and gesture in (Gesture.CLICK, Gesture.HOVER, Gesture.WAKE):
            self._sulky_until = now + C.WAKE_SULKY_S
            return self._emit(self._set_state(
                Mood.IDLE, now, f"睡觉中被 {gesture.name} 唤醒 → 委屈 3s → 空闲",
                expression=Expression.SULKY,
            ))

        if gesture in (Gesture.CLICK, Gesture.HOVER, Gesture.WAKE):
            return self._emit(self._no_change(
                now, f"手势 {gesture.name} → 开心",
                expression=Expression.HAPPY,
            ))

        # DRAG：不改变情绪态与表情（姿态由模型处理）
        return self._emit(self._no_change(now, "拖拽中"))

    def force(self, mood: Mood, now: float) -> None:
        """强制设置情绪态（跳过驻留约束），供测试或特殊恢复使用。"""

        now = float(now)
        self._state = mood
        self._state_since = now
        if mood != Mood.FOCUS:
            self._high_freq_since = None
        logger.info("状态机被强制设置为 %s", mood.name)

    # ------------------------------------------------------------------ #
    # 内部辅助
    # ------------------------------------------------------------------ #
    def _can_transition(self, now: float) -> bool:
        """最小驻留防抖判定：当前状态保持时长是否已达到 ``min_dwell_s``。"""

        return (now - self._state_since) >= self._min_dwell_s

    def _set_state(
        self,
        mood: Mood,
        now: float,
        reason: str,
        expression: Expression | None = None,
    ) -> MoodTransition:
        """执行状态切换并构造迁移描述。"""

        from_mood = self._state
        self._state = mood
        self._state_since = now
        if mood != Mood.FOCUS:
            self._high_freq_since = None
        expr = expression if expression is not None else _STATE_EXPRESSION[mood]
        return MoodTransition(
            from_mood=from_mood,
            to_mood=mood,
            expression=expr,
            reason=reason,
            timestamp=now,
            changed=(mood != from_mood),
        )

    def _no_change(
        self,
        now: float,
        reason: str,
        expression: Expression | None = None,
    ) -> MoodTransition:
        """构造一个"无状态变化"的迁移描述（可携带临时表情建议）。"""

        expr = expression if expression is not None else _STATE_EXPRESSION[self._state]
        return MoodTransition(
            from_mood=self._state,
            to_mood=self._state,
            expression=expr,
            reason=reason,
            timestamp=now,
            changed=False,
        )

    def _emit(self, transition: MoodTransition) -> MoodTransition:
        """记录并返回迁移（状态变化时写 info 日志，便于追溯 FR-05）。"""

        self._last_transition = transition
        if transition.changed:
            logger.info(
                "状态迁移 %s → %s | 表情=%s | 原因=%s | t=%.2f",
                transition.from_mood.name,
                transition.to_mood.name,
                transition.expression.name,
                transition.reason,
                transition.timestamp,
            )
        else:
            logger.debug(
                "状态保持 %s | 表情=%s | 说明=%s | t=%.2f",
                transition.to_mood.name,
                transition.expression.name,
                transition.reason,
                transition.timestamp,
            )
        return transition


__all__ = ["MoodTransition", "MoodStateMachine"]
