"""阶段 B2 · 微交互（悬停凝视 / 点击弹跳过冲 / 气泡打字感）。

覆盖三类微交互的**可测契约**：

1. 悬停凝视（B2-1）：注视向量纯函数、模型写入 ``look_x`` / ``look_y``、
   优先级 **悬停 > 表情模板 > 空闲张望**、悬停「半眯」眼（非全闭弧线眼）、
   悬停期间抑制偶发小动作。
2. 点击弹跳过冲（B2-2）：``ease_out_back`` 峰值上界 ≤ 旧幅度 1.1 倍。
3. 气泡打字感（B2-3）：前缀子串、气泡宽度恒定、``reduce_motion`` 直达终态、
   ``hide_bubble`` 停止逐字定时器（内存预算守卫）。

测试纪律（项目红线）：期望值一律**字面量**，不得用被测常量自拼期望。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel, PetPose, SurpriseKind
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.ui.bubble import BubbleWindow


def _entry() -> VocabEntry:
    return VocabEntry(
        id="n5-0001", level="N5", word="食べる", kana="たべる",
        translation="吃", meaning="进食", romaji="taberu",
    )


# --------------------------------------------------------------------------- #
# 1. 悬停凝视（B2-1）
# --------------------------------------------------------------------------- #
def test_gaze_vector_right_of_center_positive_x() -> None:
    nx, ny = motion.gaze_vector(100.0, 50.0, 80.0, 50.0, 20.0)
    assert nx == pytest.approx(1.0)
    assert ny == pytest.approx(0.0)


def test_gaze_vector_half_distance_literal() -> None:
    nx, _ny = motion.gaze_vector(90.0, 50.0, 80.0, 50.0, 20.0)
    assert nx == pytest.approx(0.5)


def test_gaze_vector_clamps_components_to_unit() -> None:
    nx, ny = motion.gaze_vector(0.0, 0.0, 80.0, 50.0, 20.0)
    assert nx == pytest.approx(-1.0)
    assert ny == pytest.approx(-1.0)


def test_gaze_vector_center_is_origin() -> None:
    assert motion.gaze_vector(80.0, 50.0, 80.0, 50.0, 20.0) == (0.0, 0.0)


def test_gaze_vector_zero_max_dist_is_safe() -> None:
    assert motion.gaze_vector(100.0, 50.0, 80.0, 50.0, 0.0) == (0.0, 0.0)


def test_hover_gaze_writes_look_offsets() -> None:
    model = PetModel()
    model.set_hover(True)
    model.set_gaze(1.0, 0.0)
    model.update(0.5, 10.0)
    # HOVER_GAZE_RANGE_PX = 4.0（字面量）
    assert model._target.look_x == pytest.approx(4.0)
    assert model._target.look_y == pytest.approx(0.0)


def test_hover_gaze_suppresses_idle_look_around() -> None:
    model = PetModel()
    now = 1.5  # LOOK_AROUND_PERIOD_S=6 → phase 0.25 → sin=1 → offset=+3.0（字面量）
    model.update(0.016, now)
    assert model._target.look_x == pytest.approx(3.0)  # 非悬停：空闲张望写入

    model.set_hover(True)
    model.set_gaze(0.0, 0.0)
    model.update(0.016, now)
    assert model._target.look_x == pytest.approx(0.0)  # 悬停：空闲张望被抑制


def test_hover_gaze_overrides_expression_template() -> None:
    model = PetModel()
    model.set_expression(Expression.SURPRISED, 5.0)  # 临时表情（插队）中
    model.set_hover(True)
    model.set_gaze(-1.0, 0.5)
    model.update(0.5, 10.0)
    # 悬停 > 表情模板：凝视方向 4.0 * (-1, 0.5) = (-4.0, 2.0)（字面量）
    assert model._target.look_x == pytest.approx(-4.0)
    assert model._target.look_y == pytest.approx(2.0)


def test_hover_uses_half_squint_not_full_arc_eye() -> None:
    model = PetModel()
    model.set_hover(True)
    model.set_gaze(0.0, 0.0)
    model.update(0.5, 10.0)
    target = model._target
    # HOVER_GAZE_OPENNESS = 0.55 / HOVER_GAZE_EYE_CURVE = 0.35（字面量）
    assert target.eye_open_l == pytest.approx(0.55)
    assert target.eye_open_r == pytest.approx(0.55)
    assert target.eye_curve == pytest.approx(0.35)
    # 低于 _draw_eye 的 arc-eye 阈值（openness<0.18 或 curve>0.6）→ 仍是实心眼
    assert target.eye_curve < 0.6


def test_hover_suppresses_surprise_action() -> None:
    model = PetModel()
    model._surprise_kind = SurpriseKind.EAR_FLICK
    model.set_hover(True)
    model.update(0.016, 1.0)
    assert model._surprise_kind is None


def test_clear_gaze_resets_direction() -> None:
    model = PetModel()
    model.set_gaze(1.0, 1.0)
    model.clear_gaze()
    assert model._gaze == (0.0, 0.0)


# --------------------------------------------------------------------------- #
# 2. 点击弹跳过冲（B2-2）
# --------------------------------------------------------------------------- #
def test_click_bounce_peak_within_1_1x_legacy() -> None:
    model = PetModel()
    steps = 400
    peak = 0.0
    for i in range(steps + 1):
        model._click_timer = C.CLICK_ANIM_S * (1.0 - i / steps)
        pose = PetPose()
        model._apply_actions(pose)
        peak = max(peak, -pose.body_y)

    legacy_peak = 3.5 * 2.2  # 旧版峰值 = BREATH_AMPLITUDE_PX * 2.2（字面量 = 7.7）
    assert peak <= legacy_peak * 1.1 + 1e-6  # 上界 ≤ 8.47（1.1 倍）
    assert peak >= 7.6                        # 确实达到原量级（未缩水为软塌塌）


# --------------------------------------------------------------------------- #
# 3. 气泡打字感（B2-3）
# --------------------------------------------------------------------------- #
def test_revealed_text_is_prefix_substring(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble._reveal = 0.5
    assert bubble._revealed_text("たべる") == "た"     # int(0.5 * 3) = 1
    bubble._reveal = 1.0
    assert bubble._revealed_text("たべる") == "たべる"
    bubble._reveal = 0.0
    assert bubble._revealed_text("たべる") == ""


def test_word_bubble_width_constant_during_typing(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)

    widths = []
    for reveal in (0.0, 0.3, 0.7, 1.0):
        bubble._reveal = reveal
        widths.append(round(bubble._measure_word().width(), 6))
    assert len(set(widths)) == 1
    # 窗口宽度 = JP_BUBBLE_MAX_WIDTH + PAD_X*2 = 240 + 20 = 260（字面量）
    assert bubble.geometry().width() == 260
    bubble.hide_bubble()


def test_reduce_motion_skips_typing_reaches_terminal_state(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_reduce_motion(True)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)
    assert bubble._reveal == 1.0
    assert not bubble._reveal_timer.isActive()
    bubble.hide_bubble()


def test_typing_starts_at_zero_and_timer_active(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_reduce_motion(False)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)
    assert bubble._reveal == 0.0
    assert bubble._reveal_timer.isActive()
    bubble.hide_bubble()


def test_advance_reveal_progresses_then_stops(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)

    bubble._advance_reveal()
    assert 0.0 < bubble._reveal < 1.0
    for _ in range(1000):
        bubble._advance_reveal()
    assert bubble._reveal == 1.0
    assert not bubble._reveal_timer.isActive()
    bubble.hide_bubble()


def test_hide_bubble_stops_reveal_timer(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_reduce_motion(False)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)
    assert bubble._reveal_timer.isActive()

    bubble.hide_bubble()
    assert not bubble._reveal_timer.isActive()
    assert bubble._reveal == 1.0


def test_show_message_does_not_use_typing(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_reduce_motion(False)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_message("你好呀~", 3.0)
    assert bubble._reveal == 1.0
    assert not bubble._reveal_timer.isActive()
    bubble.hide_bubble()


def test_word_bubble_renders_while_typing(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)
    bubble._alpha = 1.0
    bubble._reveal = 0.4

    image = QImage(bubble.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    bubble.render(painter, QPoint(0, 0))
    painter.end()

    bubble.hide_bubble()


# --------------------------------------------------------------------------- #
# 渲染器辅助（悬停基准点）
# --------------------------------------------------------------------------- #
def test_face_center_matches_canvas_geometry() -> None:
    from desktop_pet.ui.pet_renderer import PetRenderer

    cx, cy = PetRenderer.face_center(PetPose())
    assert cx == pytest.approx(80.0)  # _GEO_BODY_CX
    assert cy == pytest.approx(77.0)  # _GEO_BODY_CY（body_y = 0）
