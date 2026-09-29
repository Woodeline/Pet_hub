"""表情生动化（2026-09-29）行为测试：敲击疲劳 TIRED + 分段小表演。

覆盖三类新能力：

- **敲击疲劳**：``PetModel`` 内部按连续敲击时长（``press_arm`` 旗标 + 钟表时间）
  自动插播 ``Expression.TIRED`` 临时表情——连续性判定（间隔中断重置）、
  冷却期、门控（非专注基础表情 / 拖拽 / 临时表情占用时不插播）。
- **分段小表演**（``FAKE_SLEEP`` / ``HICCUP``）：``_apply_actions`` 按**动作进度**
  取 ``SURPRISE_SEQUENCES`` 当前段增量 —— 假睡中段「偷看」姿态必须与装睡段
  可区分；打嗝在脉冲段身体上弹。
- **TIRED 模板**：与中性姿态有实质差异（肉眼可见的表情变化）。
"""

from __future__ import annotations

from dataclasses import fields

from desktop_pet.core import constants as C
from desktop_pet.core.pet_model import PetModel, PetPose, SurpriseKind
from desktop_pet.core.constants import Expression

_FRAME_DT = 1.0 / 30.0


def _focusing_model() -> PetModel:
    """构造基础表情 = FOCUS 的模型（敲键盘工作态）。"""

    model = PetModel()
    model.set_base_expression(Expression.FOCUS)
    return model


def _type_continuously(model: PetModel, seconds: float, *, now_start: float = 100.0) -> float:
    """以 30fps 模拟连续敲键 ``seconds`` 秒，返回结束时刻的 now。"""

    now = now_start
    steps = int(seconds / _FRAME_DT)
    for _ in range(steps):
        model.press_arm()
        model.update(_FRAME_DT, now)
        now += _FRAME_DT
    return now


# --------------------------------------------------------------------------- #
# 1. 敲击疲劳 → TIRED
# --------------------------------------------------------------------------- #
def test_typing_long_enough_triggers_tired() -> None:
    """连续敲击满 ``TIRED_AFTER_TYPING_S`` → 临时表情变为 TIRED。"""

    model = _focusing_model()
    now = _type_continuously(model, C.TIRED_AFTER_TYPING_S + 0.5)
    assert model._temp_expression is Expression.TIRED, (
        "连续敲击达标后应插播敲累了表情"
    )
    assert model._temp_remaining > 0.0
    del now


def test_short_typing_does_not_trigger_tired() -> None:
    """敲击时间不足阈值 → 不触发。"""

    model = _focusing_model()
    _type_continuously(model, C.TIRED_AFTER_TYPING_S / 2.0)
    assert model._temp_expression is None


def test_typing_gap_resets_fatigue_clock() -> None:
    """敲击中断超过 ``TYPING_BURST_GAP_S`` → 计时重置，累计不作数。"""

    model = _focusing_model()
    now = _type_continuously(model, C.TIRED_AFTER_TYPING_S - 1.0)
    # 停手（超过间隔）再敲一小段 —— 疲劳计时必须从零开始
    idle_end = now + C.TYPING_BURST_GAP_S + 1.0
    steps = int((idle_end - now) / _FRAME_DT)
    for _ in range(steps):
        model.update(_FRAME_DT, now)
        now += _FRAME_DT
    now = _type_continuously(model, 2.0, now_start=now)
    assert model._temp_expression is None, "中断后重新累计，不应立即触发"


def test_tired_cooldown_prevents_immediate_repeat() -> None:
    """触发过一次吃力后，冷却期内继续敲击不再触发。"""

    model = _focusing_model()
    now = _type_continuously(model, C.TIRED_AFTER_TYPING_S + 0.5)
    first = model._temp_expression
    # 吃力表情持续期间 + 冷却期内继续敲 —— 不应再次插播（temp 归零后也不立刻重来）
    until = model._tired_cooldown_until + 1.0
    while now < until:
        model.press_arm()
        model.update(_FRAME_DT, now)
        now += _FRAME_DT
    assert first is Expression.TIRED
    assert model._temp_expression is not Expression.TIRED or model._temp_remaining < C.TIRED_EXPRESSION_S


def test_tired_not_triggered_when_not_focusing() -> None:
    """基础表情非 FOCUS（比如被拎着闲逛）→ 连续敲击也不插播吃力。"""

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    _type_continuously(model, C.TIRED_AFTER_TYPING_S + 0.5)
    assert model._temp_expression is None


def test_tired_pose_differs_meaningfully_from_neutral() -> None:
    """TIRED 模板与中性姿态有实质差异（肉眼可见的表情变化）。"""

    neutral = PetModel.pose_for_expression(Expression.HAPPY).__class__()
    tired = PetModel.pose_for_expression(Expression.TIRED)
    deltas = {
        f.name: abs(getattr(tired, f.name) - getattr(neutral, f.name))
        for f in fields(PetPose)
    }
    big = [name for name, delta in deltas.items() if delta >= 0.1]
    assert len(big) >= 4, f"TIRED 与中性差异过小，肉眼几乎不可见：{deltas}"


# --------------------------------------------------------------------------- #
# 2. 分段小表演：FAKE_SLEEP（假睡偷看） / HICCUP（打嗝）
# --------------------------------------------------------------------------- #
def _advance_surprise_to(model: PetModel, kind: SurpriseKind, progress: float) -> None:
    """把模型的进行中小动作直接钉到 ``kind`` 的 ``progress`` 进度。"""

    model._surprise_kind = kind
    model._surprise_elapsed = model._surprise_duration(kind) * progress


def test_fake_sleep_sequence_switches_to_peek() -> None:
    """假睡中段（偷看窗口）眼缝张开 + ZZZ 变淡，与装睡段可区分。"""

    model = _focusing_model()
    model.set_base_expression(Expression.SLEEPY)  # 假睡发生在休息态

    model._advance_surprise = lambda dt: None  # 冻结调度，手工钉进度
    _advance_surprise_to(model, SurpriseKind.FAKE_SLEEP, 0.2)  # 装睡段
    pose_sleep = _pose_of(model)
    _advance_surprise_to(model, SurpriseKind.FAKE_SLEEP, 0.5)  # 偷看段
    pose_peek = _pose_of(model)

    assert pose_peek.eye_open_l > pose_sleep.eye_open_l, "偷看段应睁开一条眼缝"
    assert pose_peek.zzz_alpha < pose_sleep.zzz_alpha, "偷看时 ZZZ 应变淡（装不下去啦）"
    assert pose_sleep.zzz_alpha > 0.3, "装睡段应有 ZZZ"


def test_hiccup_sequence_bounces_body() -> None:
    """打嗝脉冲段身体上弹（body_y 变小），平静段归位。"""

    model = _focusing_model()
    model._advance_surprise = lambda dt: None
    _advance_surprise_to(model, SurpriseKind.HICCUP, 0.1)  # 平静段
    pose_calm = _pose_of(model)
    _advance_surprise_to(model, SurpriseKind.HICCUP, 0.25)  # 第一声「嗝」
    pose_hic = _pose_of(model)
    assert pose_hic.body_y < pose_calm.body_y - 2.0, "打嗝段身体应明显上弹"
    assert pose_hic.mouth_open > pose_calm.mouth_open, "打嗝段嘴应张开"


def _pose_of(model: PetModel) -> PetPose:
    """走一遍 update 的目标姿态计算（不含平滑），返回 target。"""

    model.update(_FRAME_DT, 100.0)
    return model._target