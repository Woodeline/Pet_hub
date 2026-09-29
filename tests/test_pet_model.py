"""猫咪参数模型测试（FR-11 八种表情、FR-02/10 动作插队、收敛性）。"""

from __future__ import annotations

from dataclasses import asdict, fields

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel, PetPose

_ALL_EXPRESSIONS = list(Expression)


def _pose_dict(pose: PetPose) -> dict:
    return asdict(pose)


# --------------------------------------------------------------------------- #
# 1. 八种表情：完整性 + 彼此可区分（FR-11 / PRD §4.5）
# --------------------------------------------------------------------------- #
def test_expression_enum_has_eight_members() -> None:
    names = {e.name for e in Expression}
    assert names == {
        "HAPPY", "FOCUS", "SLEEPY", "SURPRISED",
        "SULKY", "YAWN", "SLEEPING", "EXCITED", "TIRED",
    }


def test_all_nine_expressions_have_distinct_poses() -> None:
    """任意两种表情的姿态不能完全相同（否则视觉无差异）。"""

    poses = {e: _pose_dict(PetModel.pose_for_expression(e)) for e in _ALL_EXPRESSIONS}
    duplicates: list[tuple[str, str]] = []
    for i, a in enumerate(_ALL_EXPRESSIONS):
        for b in _ALL_EXPRESSIONS[i + 1:]:
            if poses[a] == poses[b]:
                duplicates.append((a.name, b.name))
    assert not duplicates, f"存在姿态完全相同的表情对：{duplicates}"


def test_expression_poses_differ_by_meaningful_margin() -> None:
    """不仅不完全相同，还应有"肉眼可见"的通道差异（避免退化为默认姿态）。"""

    neutral = _pose_dict(PetPose(**C.NEUTRAL_POSE))
    for expr in _ALL_EXPRESSIONS:
        pose = _pose_dict(PetModel.pose_for_expression(expr))
        max_delta = max(abs(pose[k] - neutral.get(k, 0.0)) for k in pose)
        assert max_delta > 0.1, f"{expr.name} 与中性姿态差异过小（{max_delta}）"


@pytest.mark.parametrize(
    "expr,channel,op",
    [
        (Expression.SLEEPING, "zzz_alpha", ">0"),   # 睡觉：头顶 ZZZ
        (Expression.SLEEPING, "glow_alpha", ">0"),  # 睡觉：淡蓝光晕
        (Expression.SULKY, "tear_alpha", ">0"),     # 委屈：眼角水光
        (Expression.YAWN, "tongue_show", ">0"),     # 打呵欠：舌头
        (Expression.EXCITED, "glow_alpha", ">0"),   # 兴奋：暖黄光晕
    ],
)
def test_expression_signature_channels(expr: Expression, channel: str, op: str) -> None:
    pose = PetModel.pose_for_expression(expr)
    value = getattr(pose, channel)
    assert value > 0.0, f"{expr.name}.{channel} 应为正，实际 {value}"


def test_surprised_opens_mouth_wide() -> None:
    pose = PetModel.pose_for_expression(Expression.SURPRISED)
    assert pose.mouth_open > 0.5
    assert pose.eye_open_l > 1.0  # 圆睁


def test_happy_squints_and_smiles() -> None:
    pose = PetModel.pose_for_expression(Expression.HAPPY)
    assert pose.eye_curve > 0.5      # 弯月眯眼
    assert pose.mouth_curve > 0.5    # 上扬笑弧
    assert pose.blush_alpha > 0.5    # 腮红加深


def test_sleeping_and_yawn_have_closed_eyes() -> None:
    assert PetModel.pose_for_expression(Expression.SLEEPING).eye_open_l == 0.0
    assert PetModel.pose_for_expression(Expression.YAWN).eye_open_l == 0.0


def test_unknown_expression_does_not_crash() -> None:
    """非法 / 未知表情输入不应崩溃（回落中性姿态）。"""

    pose = PetModel.pose_for_expression("NOT_AN_EXPRESSION")  # type: ignore[arg-type]
    assert isinstance(pose, PetPose)
    neutral = _pose_dict(PetPose(**C.NEUTRAL_POSE))
    assert _pose_dict(pose) == neutral


def test_pose_for_expression_returns_independent_copy() -> None:
    p1 = PetModel.pose_for_expression(Expression.HAPPY)
    p2 = PetModel.pose_for_expression(Expression.HAPPY)
    p1.body_y = 999.0
    assert p2.body_y != 999.0


# --------------------------------------------------------------------------- #
# 2. 敲击动作插队打断（FR-02 / FR-10）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("expr", _ALL_EXPRESSIONS)
def test_press_arm_interrupts_any_expression(expr: Expression) -> None:
    """任意表情下 press_arm 都能生效（爪子按压）。"""

    model = PetModel()
    model.set_base_expression(expr)
    model.set_expression(expr, 0.0)
    model.press_arm()
    model.update(0.033, 1.0)
    pose = model.pose()
    assert max(pose.arm_l_press, pose.arm_r_press) > 0.0, f"{expr.name} 下按压未生效"


def test_press_arm_alternates_between_left_and_right() -> None:
    # 单次按压 → 右爪
    right = PetModel()
    right.press_arm()
    right.update(0.02, 1.0)
    assert right.pose().arm_r_press > right.pose().arm_l_press

    # 连按两次 → 左爪
    left = PetModel()
    left.press_arm()
    left.press_arm()
    left.update(0.02, 1.0)
    assert left.pose().arm_l_press > left.pose().arm_r_press


def test_trigger_click_sets_happy_and_bounce() -> None:
    model = PetModel()
    model.set_base_expression(Expression.SLEEPING)
    model.set_expression(Expression.SLEEPING, 0.0)
    model.update(0.02, 1.0)
    before = model.pose().body_y

    model.trigger_click()
    assert model._effective_expression() is Expression.HAPPY  # 临时表情插队
    model.update(0.02, 1.02)
    after = model.pose().body_y
    assert after != before  # 弹跳造成位移


def test_temp_expression_overrides_base_then_expires() -> None:
    model = PetModel()
    model.set_base_expression(Expression.SLEEPING)
    model.set_expression(Expression.SULKY, 0.1)
    model.update(0.01, 1.0)
    assert model._effective_expression() is Expression.SULKY

    model.update(0.2, 1.2)  # 超过 0.1s，临时表情过期
    assert model._effective_expression() is Expression.SLEEPING


def test_set_expression_zero_duration_clears_immediately() -> None:
    model = PetModel()
    model.set_expression(Expression.SULKY, 1.0)
    model.set_expression(Expression.SULKY, 0.0)
    assert model._temp_expression is None


def test_hover_increases_blush() -> None:
    plain = PetModel()
    plain.set_expression(Expression.HAPPY, 0.0)
    plain.set_base_expression(Expression.HAPPY)
    plain.update(0.033, 1.0)
    base_blush = plain.pose().blush_alpha

    hover = PetModel()
    hover.set_base_expression(Expression.HAPPY)
    hover.set_hover(True)
    hover.update(0.033, 1.0)
    assert hover.pose().blush_alpha > base_blush


def test_dragging_sets_dangling_limbs() -> None:
    model = PetModel()
    model.set_dragging(True)
    for i in range(30):  # 让姿态插值收敛
        model.update(0.033, 1.0 + i * 0.033)
    assert model.pose().arm_dangle > 0.8

    model.set_dragging(False)
    for i in range(60):
        model.update(0.033, 2.0 + i * 0.033)
    assert model.pose().arm_dangle < 0.2


# --------------------------------------------------------------------------- #
# 3. 姿态插值推进的收敛性
# --------------------------------------------------------------------------- #
def test_pose_converges_to_target_channels() -> None:
    """目标姿态最终应"到位"，而不是永远逼近。"""

    model = PetModel()
    model.set_base_expression(Expression.YAWN)
    model.set_expression(Expression.YAWN, 0.0)
    # now 固定，避免生命体征周期叠加；只观察不受呼吸/眨眼影响的通道
    for _ in range(300):
        model.update(0.033, 10.0)
    pose = model.pose()
    target = PetModel.pose_for_expression(Expression.YAWN)
    assert pose.mouth_open == pytest.approx(target.mouth_open, abs=1e-3)
    assert pose.body_squash == pytest.approx(target.body_squash, abs=1e-3)
    assert pose.tongue_show == pytest.approx(target.tongue_show, abs=1e-3)


def test_blinking_closes_eyes() -> None:
    model = PetModel()
    model.set_base_expression(Expression.FOCUS)
    model.set_expression(Expression.FOCUS, 0.0)
    model.update(0.033, 1.0)
    # 强制进入眨眼并停在半程（完全闭合点）
    model._blinking = True
    model._blink_elapsed = C.BLINK_DURATION_S / 2.0
    model.update(0.001, 1.01)
    assert model.pose().eye_open_l < 0.5


def test_life_signs_change_over_time() -> None:
    """呼吸 / 尾巴等生命体征随时间变化（FR-13/14）。"""

    a = PetModel()
    b = PetModel()
    for _ in range(5):
        a.update(0.033, 0.0)
        b.update(0.033, 1.5)
    assert a.pose().body_y != b.pose().body_y  # 呼吸相位不同


def test_pose_fields_are_all_floats() -> None:
    pose = PetModel.pose_for_expression(Expression.EXCITED)
    for f in fields(PetPose):
        assert isinstance(getattr(pose, f.name), float), f"{f.name} 不是 float"
