"""core.pet_model —— 猫咪参数模型：``PetPose`` 姿态载体 + ``PetModel`` 驱动。

**本模块禁止 import 任何图形界面（Qt/GUI）库。**

职责：
- 表情 → 目标姿态模板映射（PRD §4.5 视觉差异表，模板见 ``constants.EXPRESSION_POSES``）。
- 姿态帧率无关插值推进（``t = 1 - exp(-k*dt)``）。
- 临时动作插队打断（敲击 ``press_arm`` / 点击弹跳 ``trigger_click``，FR-10）。
- 眨眼 / 呼吸 / 尾巴摆动等生命体征（FR-13/14）。
"""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass, fields
from typing import Final, Optional

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.constants import Expression

logger = logging.getLogger(__name__)


@dataclass
class PetPose:
    """一帧猫咪姿态的全部可驱动参数（数据驱动渲染）。

    所有通道均为 ``float``；语义以中性值为基准，正值/负值方向由渲染器解释。
    """

    body_y: float = 0.0
    body_squash: float = 0.0
    head_y: float = 0.0
    head_tilt: float = 0.0
    look_x: float = 0.0
    look_y: float = 0.0
    eye_open_l: float = 1.0
    eye_open_r: float = 1.0
    eye_curve: float = 0.0
    pupil_dilate: float = 0.0
    mouth_curve: float = 0.0
    mouth_open: float = 0.0
    tongue_show: float = 0.0
    ear_l_angle: float = 0.0
    ear_r_angle: float = 0.0
    ear_l_tilt: float = 0.0
    ear_r_tilt: float = 0.0
    arm_l_press: float = 0.0
    arm_r_press: float = 0.0
    arm_dangle: float = 0.0
    arm_l_lift: float = 0.0
    arm_r_lift: float = 0.0
    finger_l_curl: float = 0.0
    finger_r_curl: float = 0.0
    tail_angle: float = 0.0
    tail_curve: float = 0.0
    #: 尾巴"逃离"位移（逻辑像素，已含强度）：根部固定、越靠尾尖位移越大。
    #: 由 :meth:`PetModel.set_tail_evade` 写入，渲染器按
    #: ``motion.ramp_weights`` 分配的权重施加到脊线上。
    tail_flee_x: float = 0.0
    tail_flee_y: float = 0.0
    blush_alpha: float = 0.0
    glow_alpha: float = 0.0
    tear_alpha: float = 0.0
    zzz_alpha: float = 0.0

    def lerp_to(self, other: "PetPose", t: float) -> "PetPose":
        """按系数 ``t``（会被钳制到 [0,1]）在本姿态与 ``other`` 之间插值。"""

        tt = motion.clamp(t, 0.0, 1.0)
        values = {
            f.name: motion.lerp(getattr(self, f.name), getattr(other, f.name), tt)
            for f in fields(self)
        }
        return PetPose(**values)


class PetModel:
    """猫咪姿态模型（由 ``PetWindow`` 每帧驱动推进）。"""

    def __init__(self) -> None:
        """构造模型，初始为中性姿态与空闲基础表情。"""

        self._current: PetPose = self.pose_for_expression(Expression.HAPPY)
        self._target: PetPose = self._current.lerp_to(self._current, 1.0)

        # 生命体征计时
        self._blink_timer: float = motion.random_interval(C.BLINK_MIN_S, C.BLINK_MAX_S)
        self._blinking: bool = False
        self._blink_elapsed: float = 0.0

        # 敲击按压
        self._press_timer: float = 0.0
        self._press_arm: int = 0

        # 交互状态
        self._dragging: bool = False
        self._hovering: bool = False

        # 尾巴避让（鼠标靠近 / 触碰尾巴）：目标强度、逃离方向（单位向量）、当前平滑值
        self._tail_evade_target: float = 0.0
        self._tail_evade_dir: tuple[float, float] = (0.0, 0.0)
        self._tail_evade: float = 0.0

        # 临时动作（插队打断）
        self._temp_action_until: float = 0.0
        self._temp_expression: Optional[Expression] = None
        self._temp_remaining: float = 0.0

        # 点击弹跳
        self._click_timer: float = 0.0

        self._base_expression: Expression = Expression.HAPPY
        self._rng: random.Random = random.Random()

    # ------------------------------------------------------------------ #
    # 外部设置接口
    # ------------------------------------------------------------------ #
    def set_expression(self, expr: Expression, duration: float) -> None:
        """设置一个**临时**表情（插队打断当前基础表情），持续 ``duration`` 秒。

        Args:
            expr: 临时表情。
            duration: 持续秒数（<=0 视为立即清除）。
        """

        if duration <= 0.0:
            self._temp_expression = None
            self._temp_remaining = 0.0
            return
        self._temp_expression = expr
        self._temp_remaining = float(duration)

    def set_base_expression(self, expr: Expression) -> None:
        """设置基础表情（情绪态常态表现对应的表情）。"""

        self._base_expression = expr

    def trigger_click(self) -> None:
        """点击反应：开心表情 + 短促弹跳（FR-27，持续 ``CLICK_ANIM_S``）。"""

        self._temp_expression = Expression.HAPPY
        self._temp_remaining = C.CLICK_ANIM_S
        self._click_timer = C.CLICK_ANIM_S

    def set_dragging(self, active: bool) -> None:
        """设置拖拽状态（被拎起姿态，FR-29）。"""

        self._dragging = bool(active)

    def set_hover(self, active: bool) -> None:
        """设置悬停抚摸状态（FR-28，眯眼 + 腮红加深）。"""

        self._hovering = bool(active)

    def set_tail_evade(self, amount: float, dir_x: float, dir_y: float) -> None:
        """设置尾巴**避让**目标（鼠标靠近 / 触碰尾巴时的反应）。

        由 UI 层按「光标到尾巴中心线的距离」与「该往哪躲」每帧写入
        （见 ``motion.tail_evade_amount`` / ``motion.flee_direction`` 与
        ``ui.pet_window.PetWindow``）。实际强度在本模型内做**非对称平滑**：
        逼近快、回落慢 → 得到"惊觉后缓缓放松"的余韵，而不是硬切。

        Args:
            amount: 避让强度 ``0→1``（``0`` = 无反应）。
            dir_x: 逃跑方向单位向量 x 分量（由 ``motion.flee_direction`` 给出）。
            dir_y: 逃跑方向单位向量 y 分量。
        """

        if self._dragging:
            # 被拎起时尾巴本就整体外摆，再叠加避让会互相打架
            self._tail_evade_target = 0.0
            return
        self._tail_evade_target = motion.clamp(amount, 0.0, 1.0)
        # 方向在强度衰减期间必须**保持住**：否则回落到 0 的最后一帧方向会被写成
        # (0,0)，尾巴会瞬移回原位而不是平滑收回。
        norm = math.hypot(dir_x, dir_y)
        if norm > 1e-9:
            self._tail_evade_dir = (dir_x / norm, dir_y / norm)

    def tail_evade(self) -> tuple[float, tuple[float, float]]:
        """返回当前尾巴避让状态 ``(强度, 逃跑方向单位向量)``（供测试与调试观察）。"""

        return self._tail_evade, self._tail_evade_dir

    def is_dragging(self) -> bool:
        """是否处于被拎起（拖拽）状态。

        供上层（如 ``PetAppController``）在拖拽期间抑制敲击反馈，避免
        "双手下垂外摆" 与 "落指" 在同一帧叠加（需求 2）。
        """

        return self._dragging

    def press_arm(self) -> None:
        """触发一次敲键盘按压：左右爪交替（FR-02）。"""

        self._press_arm = 1 - self._press_arm
        self._press_timer = C.PRESS_ANIM_S

    # ------------------------------------------------------------------ #
    # 帧推进
    # ------------------------------------------------------------------ #
    def update(self, dt: float, now: float) -> None:
        """推进一帧。

        Args:
            dt: 帧间隔（秒）。
            now: 当前时刻（秒，来自 ``time.monotonic()``）。
        """

        dt = max(0.0, float(dt))
        now = float(now)

        self._tick_timers(dt)

        expr = self._effective_expression()
        target = self.pose_for_expression(expr)
        self._apply_life_signs(target, now)
        self._apply_actions(target)

        t = motion.exponential_smoothing_t(C.POSE_SMOOTH_K, dt)
        self._current = self._current.lerp_to(target, t)
        # 敲击属**瞬时反馈**（FR-02：按键→首帧 <100ms），必须在全局平滑之后
        # 直接落到当前姿态上，否则 30fps 下每帧仅靠拢 ~26%，幅度会被吃掉 3/4。
        self._apply_keystroke(self._current)
        self._target = target

    def pose(self) -> PetPose:
        """返回当前姿态（供渲染器读取）。"""

        return self._current

    # ------------------------------------------------------------------ #
    # 表情模板
    # ------------------------------------------------------------------ #
    @staticmethod
    def pose_for_expression(expr: Expression) -> PetPose:
        """根据表情返回目标姿态模板（中性姿态叠加该表情的增量）。

        Args:
            expr: 表情枚举。

        Returns:
            该表情对应的 :class:`PetPose`（可安全修改）。
        """

        values: dict[str, float] = dict(C.NEUTRAL_POSE)
        overrides = C.EXPRESSION_POSES.get(expr)
        if overrides:
            values.update(overrides)
        # 过滤非 PetPose 字段，避免常量表笔误导致构造失败
        valid_fields = {f.name for f in fields(PetPose)}
        filtered = {k: v for k, v in values.items() if k in valid_fields}
        return PetPose(**filtered)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _effective_expression(self) -> Expression:
        """返回当前生效的表情（临时 > 悬停 > 基础）。"""

        if self._temp_expression is not None:
            return self._temp_expression
        if self._hovering:
            return Expression.HAPPY
        return self._base_expression

    def _tick_timers(self, dt: float) -> None:
        """推进所有内部计时器。"""

        # 临时表情倒计时
        if self._temp_remaining > 0.0:
            self._temp_remaining = max(0.0, self._temp_remaining - dt)
            if self._temp_remaining == 0.0:
                self._temp_expression = None

        # 眨眼调度的推进（FR-14）
        if self._blinking:
            self._blink_elapsed += dt
            if self._blink_elapsed >= C.BLINK_DURATION_S:
                self._blinking = False
                self._blink_elapsed = 0.0
                self._blink_timer = motion.random_interval(
                    C.BLINK_MIN_S, C.BLINK_MAX_S, self._rng
                )
        else:
            self._blink_timer -= dt
            if self._blink_timer <= 0.0:
                self._blinking = True
                self._blink_elapsed = 0.0

        # 敲击按压倒计时
        if self._press_timer > 0.0:
            self._press_timer = max(0.0, self._press_timer - dt)

        # 点击弹跳倒计时
        if self._click_timer > 0.0:
            self._click_timer = max(0.0, self._click_timer - dt)

        # 尾巴避让：非对称平滑（逼近快 / 回落慢），帧率无关
        evade_rate = (
            C.TAIL_EVADE_ATTACK_K
            if self._tail_evade_target > self._tail_evade
            else C.TAIL_EVADE_RELEASE_K
        )
        step = motion.exponential_smoothing_t(evade_rate, dt)
        self._tail_evade += (self._tail_evade_target - self._tail_evade) * step

    def _apply_life_signs(self, target: PetPose, now: float) -> None:
        """在目标姿态上叠加呼吸 / 尾巴摆动 / 耳朵抖动 / 眨眼 / 张望。"""

        # 呼吸起伏（FR-14）——幅度随睡姿更柔
        breath_amplitude = C.BREATH_AMPLITUDE_PX
        breath = motion.breath_offset(now, C.BREATH_PERIOD_S, breath_amplitude)
        target.body_y += breath
        target.head_y += breath * 0.5

        # 尾巴摆动（FR-13）——拖拽/睡觉时减弱或僵直
        if not self._dragging:
            period = motion.lerp(C.TAIL_MIN_S, C.TAIL_MAX_S, target.tail_curve)
            amp = C.TAIL_AMPLITUDE_DEG * (0.35 + target.tail_curve)
            # 睡觉态尾巴幅度更小
            if self._effective_expression() == Expression.SLEEPING:
                amp *= 0.25
            target.tail_angle += motion.tail_angle(now, period, amp)

        # 尾巴避让（鼠标靠近 / 触碰）：沿"远离光标"的方向整体让开。
        # 只写入位移向量，具体分配（根部 0 → 尾尖最大）由渲染器按脊线权重完成。
        # 叠加在基础摆动之上 → 得到「常态慢摆 + 受扰快速躲闪」两层动态。
        if self._tail_evade > 1e-4:
            reach = C.TAIL_EVADE_MAX_PX * self._tail_evade
            target.tail_flee_x = self._tail_evade_dir[0] * reach
            target.tail_flee_y = self._tail_evade_dir[1] * reach

        # 耳朵偶发抖动（FR-13）——仅在非睡觉态明显
        if self._effective_expression() != Expression.SLEEPING:
            twitch = motion.ear_twitch(now, C.EAR_TWITCH_MIN_S, C.EAR_TWITCH_AMPLITUDE_DEG)
            target.ear_l_tilt += twitch
            # 左右耳错相位
            target.ear_r_tilt += motion.ear_twitch(
                now + C.EAR_TWITCH_MIN_S * 0.3,
                C.EAR_TWITCH_MIN_S,
                C.EAR_TWITCH_AMPLITUDE_DEG * 0.8,
            )

        # 空闲张望（FR-06）
        if self._base_expression in (Expression.HAPPY,) and self._temp_expression is None:
            target.look_x += motion.look_around_offset(now)

        # 眨眼（FR-14）——仅对睁眼状态生效
        if self._blinking:
            openness = motion.blink_curve(self._blink_elapsed, C.BLINK_DURATION_S)
            target.eye_open_l *= openness
            target.eye_open_r *= openness

    def _apply_actions(self, target: PetPose) -> None:
        """在目标姿态上叠加**非瞬时**动作：点击弹跳 / 拖拽下垂 / 悬停腮红 / 身体下沉。

        .. note::
           敲击的**瞬时通道**（``arm_*_press`` / ``arm_*_lift`` / ``finger_*_curl``）
           **不在此处写入 target** —— 它们会被全局姿态平滑 ``POSE_SMOOTH_K``
           吃掉大半幅度。改由 :meth:`_apply_keystroke` 在平滑**之后**直接叠加到
           当前姿态。此处只处理可缓动的 ``body_squash``。
        """

        # 敲击时身体轻微下沉（随身体缓动，保留在平滑通道内）
        # 拖拽（被拎起）期间不叠加敲击反馈，避免「既下垂又落指」的姿态冲突。
        press, _lift, _curl, active = self.keystroke_state()
        if active and not self._dragging:
            target.body_squash -= C.PRESS_BODY_SQUASH * press

        # 点击弹跳（FR-27）
        if self._click_timer > 0.0:
            progress = 1.0 - (self._click_timer / C.CLICK_ANIM_S)  # 0 → 1
            bounce = motion.ease_out_bounce(progress * 2.0) if progress < 0.5 else \
                motion.ease_out_bounce((1.0 - progress) * 2.0)
            target.body_y -= C.BREATH_AMPLITUDE_PX * 2.2 * bounce

        # 被拎起姿态（FR-29）：四肢下垂 + 轻微上提
        if self._dragging:
            target.arm_dangle = max(target.arm_dangle, 1.0)
            target.body_y -= 2.0
            target.body_squash -= 0.02

        # 悬停抚摸：腮红加深（FR-28）
        if self._hovering:
            target.blush_alpha = min(1.0, target.blush_alpha + 0.25)

    def keystroke_state(self) -> tuple[float, float, float, bool]:
        """返回当前敲击包络 ``(press, lift, curl, active)``。

        ``active`` 表示本次敲击动画是否仍在进行（``_press_timer > 0``）。
        ``press`` / ``curl`` 作用于**活动侧**（由 :meth:`_apply_keystroke` 落到
        ``arm_*_press`` / ``finger_*_curl``），``lift`` 作用于**非活动侧**的
        ``arm_*_lift``；``press`` 另供 :meth:`_apply_actions` 计算 ``body_squash``。
        供 :meth:`_apply_actions` 与 :meth:`_apply_keystroke` 共用，避免重复计算包络。
        """

        if self._press_timer <= 0.0:
            return 0.0, 0.0, 0.0, False
        elapsed = C.PRESS_ANIM_S - self._press_timer  # 0 → PRESS_ANIM_S
        press, lift, curl = self._keystroke_envelope(elapsed)
        return press, lift, curl, True

    def _apply_keystroke(self, current: PetPose) -> None:
        """把敲击的瞬时通道**直接绝对赋值**到当前姿态（绕开全局平滑）。

        在 ``_current`` 完成 ``lerp_to`` 之后调用；用**绝对赋值**而非累加，
        保证与 :meth:`_apply_actions` 不会重复叠加。

        左右分工（"活动侧落指、另一侧抬腕"，最接近真实打字）：

        * **活动侧**：落指 ``arm_*_press`` + 屈指 ``finger_*_curl``；
        * **非活动侧**：抬腕 ``arm_*_lift`` —— 取 ``max`` 防止换边瞬间回跳。

        抬腕落在非活动侧后，抬腕与落指**不在同一只手**，因此
        18px 的下压位移不会被 13.5px 的上提抵消（幅度得以保全）；且抬腕在
        "落指阶段"即升到位，**高频连打时依然可见**（间隔 < ``PRESS_DOWN_S``
        时活动侧来不及进入回弹，但非活动侧已抬起）。

        拖拽（被拎起）时不叠加任何敲击通道，避免 ``arm_dangle≈1``（双手外摆
        下垂）与 ``arm_*_press``（落指）同帧并存（需求 2）。
        """

        if self._dragging:
            return
        press, lift, curl, active = self.keystroke_state()
        if not active:
            return
        if self._press_arm == 0:
            current.arm_l_press = press
            current.finger_l_curl = curl
            current.arm_r_lift = max(current.arm_r_lift, lift)
        else:
            current.arm_r_press = press
            current.finger_r_curl = curl
            current.arm_l_lift = max(current.arm_l_lift, lift)

    @staticmethod
    def _keystroke_envelope(elapsed: float) -> tuple[float, float, float]:
        """单次敲击的时间包络，返回 ``(落指 press, 抬腕 lift, 手指弯曲 curl)``。

        时间线（``lift`` 与 ``press`` 在"落指阶段"**同升**，但作用于**不同的手**）：

        * ``[0, PRESS_DOWN_S)`` —— **落指 + 抬腕**：``press`` 0→1（缓出）驱动
          **活动侧**掌心下压；``curl`` 0→1 驱动活动侧屈指；``lift`` 0→1（缓出）
          驱动**非活动侧**手腕抬起。抬腕在此阶段即升到位 →
          即便敲击间隔 < ``PRESS_DOWN_S``（高频连打）也看得到抬腕。
        * ``[PRESS_DOWN_S, PRESS_ANIM_S)`` —— **回弹**：``press`` 1→0 掌心回落，
          ``curl`` 1→0 手指舒展；``lift`` 保持 1.0（由非活动侧持有，待其换边成为
          活动侧后由 ``lerp_to`` 自然衰减）。

        Args:
            elapsed: 自本次敲击开始的秒数（可为负，表示尚未开始）。

        Returns:
            三元组，各分量均已乘上对应峰值常量（默认峰值 1.0）。
        """

        if elapsed <= 0.0:
            return 0.0, 0.0, 0.0

        down = C.PRESS_DOWN_S
        total = C.PRESS_ANIM_S

        if elapsed < down:
            u = elapsed / down
            press = motion.ease_out_cubic(u)
            lift = motion.ease_out_cubic(u)
            curl = motion.ease_out_cubic(u)
        elif elapsed < total:
            u = (elapsed - down) / max(1e-6, C.PRESS_REBOUND_S)
            press = 1.0 - motion.ease_in_out(u)
            lift = 1.0
            curl = 1.0 - motion.ease_in_out(u)
        else:
            press = 0.0
            lift = 0.0
            curl = 0.0

        return press, lift * C.PRESS_LIFT_PEAK, curl * C.PRESS_CURL_PEAK


__all__ = ["PetPose", "PetModel"]
