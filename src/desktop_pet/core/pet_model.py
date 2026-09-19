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
from enum import Enum, auto
from typing import Optional

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.constants import Expression

logger = logging.getLogger(__name__)


class SurpriseKind(Enum):
    """偶发「小动作」枚举（阶段 A5-2）。

    **独立于** :class:`~desktop_pet.core.constants.Expression`（后者成员数被
    ``test_expression_count_matches_prd`` 锁定 == 8，绝不可扩展）。每种小动作对应
    ``constants.SURPRISE_POSES`` 中的一组姿态增量，仅复用现有姿态通道。
    """

    STRETCH = auto()        # 伸懒腰
    TAIL_FLICK = auto()     # 甩尾
    EAR_FLICK = auto()      # 抖耳
    GLANCE_CORNER = auto()  # 看角落
    # —— 换姿态（阶段 C1-2）：时长更长（``POSTURE_DURATION_S``），观感是「摆个姿势」——
    LOAF = auto()           # 趴着
    LIE_SIDE = auto()       # 侧卧


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
        #: 悬停注视方向（归一化 ``[-1, 1]``，由 UI 每帧写入；阶段 B2-1）。
        #: ``(0, 0)`` = 看向正前方。仅悬停激活期间生效（P5：悬停 > 表情模板 > 空闲张望）。
        self._gaze: tuple[float, float] = (0.0, 0.0)

        # 尾巴避让（鼠标靠近 / 触碰尾巴）：目标强度、逃离方向（单位向量）、当前平滑值
        self._tail_evade_target: float = 0.0
        self._tail_evade_dir: tuple[float, float] = (0.0, 0.0)
        self._tail_evade: float = 0.0

        # 临时动作（插队打断）
        self._temp_expression: Optional[Expression] = None
        self._temp_remaining: float = 0.0

        # 点击弹跳
        self._click_timer: float = 0.0

        self._base_expression: Expression = Expression.HAPPY
        self._rng: random.Random = random.Random()

        # 呼吸：**epoch 锚定相位**（阶段 A5-1，v1.1 R2）
        #   phase = ((now - epoch) / period) mod 1 —— 是 ``(now, 状态)`` 的**纯函数**：
        #   ``now`` 冻结时相位恒定（FR-34「恒定时钟帧率无关」不被破坏）；周期**只在
        #   回绕点**变更（该处相位 ≈ 0/1、``sin`` ≈ 0），相位值与导数均连续 →
        #   根治「周期中途变更 → 相位瞬跳（打嗝）」。
        self._breath_period: float = C.BREATH_PERIOD_S
        self._breath_epoch: Optional[float] = None  # 本轮呼吸周期锚点（首帧惰性锚定）
        self._breath_phase: float = 0.0             # 最近一帧相位（供测试/调试观察）

        # 偶发小动作（阶段 A5-2）：下一次触发倒计时 / 当前动作 / 已进行时长 / 平静累计
        self._surprise_timer: float = motion.random_interval(
            C.SURPRISE_MIN_S, C.SURPRISE_MAX_S, self._rng
        )
        self._surprise_kind: Optional[SurpriseKind] = None
        self._surprise_elapsed: float = 0.0
        self._calm_seconds: float = 0.0
        # 「减少动效」开关（由 UI/app 层写入；开启时不调度、不叠加小动作）
        self._reduce_motion: bool = False

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

    def set_gaze(self, nx: float, ny: float) -> None:
        """写入悬停注视方向（阶段 B2-1）。

        参数为**归一化**偏移 ``[-1, 1]``（各分量钳制）。仅由 UI 层在**悬停激活期间**
        每帧调用 —— 光标屏幕坐标 → 逻辑画布坐标的换算在 ``ui.pet_window``、
        方向归一化在 :func:`desktop_pet.core.motion.gaze_vector`（core 纯计算）。
        模型在 :meth:`_apply_life_signs` 中把它转成 ``look_x`` / ``look_y`` 偏移，
        优先级 **悬停 > 表情模板 > 空闲张望**（P5）。

        Args:
            nx: 水平归一化偏移（+ 向右）。
            ny: 垂直归一化偏移（+ 向下）。
        """

        self._gaze = (motion.clamp(nx, -1.0, 1.0), motion.clamp(ny, -1.0, 1.0))

    def clear_gaze(self) -> None:
        """复位注视方向为正前方（悬停结束时由 UI 调用）。"""

        self._gaze = (0.0, 0.0)

    def set_reduce_motion(self, active: bool) -> None:
        """设置「减少动效」开关（对应 prefers-reduced-motion）。

        开启时**不调度、不叠加**偶发小动作（阶段 A5-2）；呼吸/尾摆等常态生命体征照旧。
        由 app 层（``PetAppController``）随配置注入，与既有 ``ui.motion_ui`` 的做法一致。
        """

        self._reduce_motion = bool(active)

    @property
    def calm_seconds(self) -> float:
        """累计「安静在场」时长（秒，只读）。

        语义与 :meth:`_advance_surprise` 的调度**同源**：仅当门控（:meth:`_surprise_allowed`）
        全部满足时才累加，否则**立即清零**。因此它是模型侧唯一权威的空闲度量 —— 阶段 C 的
        空闲游走**必须**复用它做门控（v1.1 §G3：避免两套「空闲」口径漂移），否则宠物会在
        用户正常使用期间也持续游走，表现为**位置漂移**。

        注：``reduce_motion`` 开启时门控恒 False → ``calm_seconds`` 恒为 0 → 游走自然被抑制。
        """

        return self._calm_seconds

    def is_quiet_for_wander(self) -> bool:
        """是否安静到允许空闲游走（复用 ``REST_THRESHOLD_S`` 同一空闲阈值）。"""

        return self._calm_seconds >= C.REST_THRESHOLD_S


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

        # 偶发小动作调度（受门控约束）
        self._advance_surprise(dt)

    # ------------------------------------------------------------------ #
    # 偶发小动作调度（阶段 A5-2）
    # ------------------------------------------------------------------ #
    def _surprise_allowed(self) -> bool:
        """当前是否允许推进 / 触发小动作（门控，v1.1 G3）。

        仅当**全部**满足时才允许：非 ``reduce_motion``、非拖拽、**非悬停**、无临时表情、
        基础表情属 IDLE / REST 对应态（``HAPPY`` / ``SLEEPY``）——即「安静地在场」。

        ``HAPPY`` / ``SLEEPY`` 正是状态机按 ``IDLE_START_S`` / ``REST_THRESHOLD_S``
        判定 IDLE / REST 后给出的基础表情，故此处**复用同一空闲定义**，不再另设阈值，
        避免与阶段 C 的游走出现两套「空闲」口径漂移。

        .. note::
           阶段 B2-1 起把**悬停**也纳入抑制：悬停是「被抚摸」的**主动交互**态，
           宠物正专注看向光标；此时若叠加小动作（尤其带 ``look_x`` 的看角落 / 甩尾）
           会与凝视方向打架（P5：悬停 > 表情模板）。
        """

        if self._reduce_motion or self._dragging or self._hovering:
            return False
        if self._temp_expression is not None:
            return False
        return self._base_expression in (Expression.HAPPY, Expression.SLEEPY)

    def _pick_surprise(self) -> SurpriseKind:
        """随机挑一种小动作（走注入的 ``_rng``，可复现）。"""

        return self._rng.choice(list(SurpriseKind))

    @staticmethod
    def _surprise_duration(kind: SurpriseKind) -> float:
        """返回该小动作的持续时长（秒）。

        「换姿态」成员（``constants.SURPRISE_POSTURE_KINDS`` 所列：趴着 / 侧卧）用更长的
        ``POSTURE_DURATION_S``——需要维持一会儿才像「摆个姿势」；其余小动作沿用短促的
        ``SURPRISE_DURATION_S``。以 ``.name`` 查表（constants 不能 import pet_model，同
        ``SURPRISE_POSES`` 先例）。
        """

        if kind.name in C.SURPRISE_POSTURE_KINDS:
            return C.POSTURE_DURATION_S
        return C.SURPRISE_DURATION_S

    def _advance_surprise(self, dt: float) -> None:
        """推进小动作调度：累计平静时长、倒计时触发、换帧推进、收尾重排。"""

        if not self._surprise_allowed():
            # 门控失效：立即取消进行中的动作，避免「不该动时残留姿态」；平静计时清零
            self._calm_seconds = 0.0
            if self._surprise_kind is not None:
                self._surprise_kind = None
                self._surprise_elapsed = 0.0
            return

        # 平静时长达到 REST_THRESHOLD_S 后才开始进入触发倒计时（复用同一空闲阈值）
        if self._calm_seconds < C.REST_THRESHOLD_S:
            self._calm_seconds += dt
            return

        if self._surprise_kind is None:
            self._surprise_timer -= dt
            if self._surprise_timer <= 0.0:
                self._surprise_kind = self._pick_surprise()
                self._surprise_elapsed = 0.0
            return

        self._surprise_elapsed += dt
        if self._surprise_elapsed >= self._surprise_duration(self._surprise_kind):
            self._surprise_kind = None
            self._surprise_elapsed = 0.0
            self._surprise_timer = motion.random_interval(
                C.SURPRISE_MIN_S, C.SURPRISE_MAX_S, self._rng
            )

    def _breath_phase_for(self, now: float) -> float:
        """按 **epoch 锚定** 求当前呼吸相位 ``[0, 1)``（阶段 A5-1，v1.1 R2）。

        相位 = ``((now - epoch) / period) mod 1``，``epoch`` 为当前呼吸周期的锚点、
        ``period`` 为本轮周期（回绕时以 ``BREATH_PERIOD_S·(1 ± BREATH_JITTER)`` 重抽）。
        两个关键性质：

        * **纯函数性**：相位只依赖 ``now`` 与内部状态，``now`` 冻结时相位恒定 →
          FR-34「恒定时钟下 30fps/60fps 精确一致」不被破坏。
        * **无瞬跳**：周期**只在** ``delta >= period`` 的回绕点重抽，而该处相位 ≈ 0/1、
          ``sin`` ≈ 0，故呼吸位移的**值与导数都连续** —— 恰是旧实现（周期中途变更 →
          相位瞬跳「打嗝」）的反面。

        首帧惰性锚定：``epoch`` 取「不大于 ``now`` 的最近整周期边界」，令首帧相位等于旧
        ``cycle_phase(now, period)``（保持既有首帧语义），且 ``delta`` 恒落在 ``[0, period)``
        内 —— 避免 ``time.monotonic()`` 绝对数值较大时每帧都误触发回绕。

        Args:
            now: 当前时刻（秒）。

        Returns:
            本轮相位，值域 ``[0, 1)``。
        """

        if self._breath_period <= 0.0:  # 防御：避免除零
            self._breath_period = C.BREATH_PERIOD_S
        if self._breath_epoch is None:
            offset = motion.cycle_phase(now, self._breath_period) * self._breath_period
            self._breath_epoch = now - offset
        delta = now - self._breath_epoch
        if delta < 0.0:  # now 回退（含负 dt 场景）→ 重锚，防负相位
            self._breath_epoch = now
            self._breath_period = C.BREATH_PERIOD_S
            delta = 0.0
        if delta >= self._breath_period:  # 仅在回绕点变更周期 → 相位值与导数连续
            self._breath_epoch += self._breath_period
            self._breath_period = motion.random_interval(
                C.BREATH_PERIOD_S * (1.0 - C.BREATH_JITTER),
                C.BREATH_PERIOD_S * (1.0 + C.BREATH_JITTER),
                self._rng,
            )
            delta = now - self._breath_epoch
        if self._breath_period <= 0.0:  # 重抽后仍防御
            self._breath_period = C.BREATH_PERIOD_S
        self._breath_phase = (delta / self._breath_period) % 1.0
        return self._breath_phase

    def _apply_life_signs(self, target: PetPose, now: float) -> None:
        """在目标姿态上叠加呼吸 / 尾巴摆动 / 耳朵抖动 / 眨眼 / 张望。"""

        # 呼吸起伏（FR-14）——由 epoch 锚定相位求得（周期微随机、相位连续，A5-1）
        breath_amplitude = C.BREATH_AMPLITUDE_PX
        breath = motion.breath_offset_phased(
            self._breath_phase_for(now), breath_amplitude
        )
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

        # 悬停凝视（阶段 B2-1）—— **绝对赋值**，覆盖模板 / 小动作写入的 look_*
        # （P5 优先级：悬停 > 表情模板 > 空闲张望）。方向由 UI 每帧经 ``set_gaze`` 写入。
        # 必须在「空闲张望」**之前**执行：这样「悬停期间不写空闲张望」这一守卫才是
        # 可观测的（否则后写的绝对赋值会把空闲偏移抹掉，守卫形同虚设、也无法被变异测试捕获）。
        if self._hovering:
            target.look_x = self._gaze[0] * C.HOVER_GAZE_RANGE_PX
            target.look_y = self._gaze[1] * C.HOVER_GAZE_RANGE_PX

        # 空闲张望（FR-06）—— 悬停期间不写入（P5：悬停 > 空闲张望）
        if (
            self._base_expression in (Expression.HAPPY,)
            and self._temp_expression is None
            and not self._hovering
        ):
            target.look_x += motion.look_around_offset(now)

        # 眨眼（FR-14）——仅对睁眼状态生效；右眼比左眼晚 BLINK_EYE_DELAY_S 起闭（A5-3）
        if self._blinking:
            openness_l = motion.blink_curve(self._blink_elapsed, C.BLINK_DURATION_S)
            openness_r = motion.blink_curve(
                max(0.0, self._blink_elapsed - C.BLINK_EYE_DELAY_S), C.BLINK_DURATION_S
            )
            target.eye_open_l *= openness_l
            target.eye_open_r *= openness_r

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

        # 点击弹跳（FR-27）：压扁 → 弹起 → 轻微过冲回落（阶段 B2-2）
        # ``ease_out_back`` 峰值 ≈1.1 → 最大位移 = CLICK_BOUNCE_PX * 1.1 ≈ 7.7px，
        # 与旧 ``ease_out_bounce`` 版峰值（BREATH_AMPLITUDE_PX*2.2）持平 → 不越脏区。
        if self._click_timer > 0.0:
            progress = 1.0 - (self._click_timer / C.CLICK_ANIM_S)  # 0 → 1
            u = progress * 2.0 if progress < 0.5 else (1.0 - progress) * 2.0  # 0→1→0
            bounce = motion.ease_out_back(u)
            target.body_y -= C.CLICK_BOUNCE_PX * bounce

        # 被拎起姿态（FR-29）：四肢下垂 + 轻微上提
        if self._dragging:
            target.arm_dangle = max(target.arm_dangle, 1.0)
            target.body_y -= 2.0
            target.body_squash -= 0.02

        # 悬停抚摸：腮红加深（FR-28）+ 半眯凝视眼（阶段 B2-1）
        if self._hovering:
            target.blush_alpha = min(1.0, target.blush_alpha + 0.25)
            # 悬停本是 HAPPY 模板（全闭弧线眼 0.12 / curve 1.0）——会把瞳孔完全遮住，
            # 凝视不可见。改为「半眯」：抬升张开度、压低弯曲度，保持实心眼 + 瞳孔可见。
            target.eye_open_l = max(target.eye_open_l, C.HOVER_GAZE_OPENNESS)
            target.eye_open_r = max(target.eye_open_r, C.HOVER_GAZE_OPENNESS)
            target.eye_curve = min(target.eye_curve, C.HOVER_GAZE_EYE_CURVE)

        # 偶发小动作（阶段 A5-2）：按包络把姿态增量叠加到目标姿态
        # 「换姿态」（LOAF / LIE_SIDE）用更长的 POSTURE_DURATION_S（阶段 C1-2），
        # 包络时长必须与 _advance_surprise 的收尾阈值一致，否则姿态会被提前抹掉。
        if self._surprise_kind is not None:
            envelope = motion.surprise_envelope(
                self._surprise_elapsed, self._surprise_duration(self._surprise_kind)
            )
            for channel, delta in C.SURPRISE_POSES.get(self._surprise_kind.name, {}).items():
                if hasattr(target, channel):
                    setattr(target, channel, getattr(target, channel) + delta * envelope)

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


__all__ = ["SurpriseKind", "PetPose", "PetModel"]
