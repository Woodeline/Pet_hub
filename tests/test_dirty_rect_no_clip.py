"""脏区（收窄重绘矩形）不裁剪回归测试 —— FR-35 收窄刷新引入的新风险守护。

背景：``PetWindow.pet_rect()`` 改为返回 :meth:`PetRenderer.body_bounds` 计算的
**收窄矩形**（光晕态回退整窗）。若 ``body_bounds`` 算窄了，猫会被静默裁掉一角，
而普通渲染用例发现不了。本文件用「QImage 实际渲染 → 统计非透明像素真实包围盒 →
断言 ⊆ pet_rect()」的方式，把这条约束固化为**永久回归**。

覆盖：8 种表情 + 敲击/拖拽/悬停姿态 × 3 档缩放；光晕阈值边界 (0.009/0.010/0.011)。
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel, PetPose
from desktop_pet.ui.pet_renderer import PetRenderer
from desktop_pet.ui.pet_window import PetWindow

_SCALES = (0.8, 1.0, 1.2)


class _StubModel:
    """只提供 :meth:`pose` 的桩模型，便于把任意姿态塞进 PetWindow。"""

    def __init__(self, pose: PetPose) -> None:
        self._pose = pose

    def pose(self) -> PetPose:
        return self._pose


# --------------------------------------------------------------------------- #
# 渲染 + 真实包围盒
# --------------------------------------------------------------------------- #
def _render(renderer: PetRenderer, pose: PetPose, scale: float) -> QImage:
    w = int(round(C.BASE_W * scale))
    h = int(round(C.BASE_H * scale))
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        renderer.paint(painter, pose, scale, QSize(w, h))
    finally:
        painter.end()
    return image


def _opaque_bbox(image: QImage) -> tuple[int, int, int, int] | None:
    """返回非透明像素的真实包围盒 (min_x, min_y, max_x, max_y)；全透明则 None。"""

    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        row = y * stride
        base = row + 3  # ARGB32 小端：byte[3] 为 alpha
        for x in range(w):
            if data[base + x * 4] != 0:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return None
    return (min_x, min_y, max_x, max_y)


def _assert_contained(bbox, rect, label: str) -> None:
    min_x, min_y, max_x, max_y = bbox
    assert rect.left() <= min_x, f"{label}: 左边缘被裁（内容 {min_x} < pet_rect.left {rect.left()}）"
    assert rect.top() <= min_y, f"{label}: 上边缘被裁（内容 {min_y} < pet_rect.top {rect.top()}）"
    assert rect.right() >= max_x, f"{label}: 右边缘被裁（内容 {max_x} > pet_rect.right {rect.right()}）"
    assert rect.bottom() >= max_y, f"{label}: 下边缘被裁（内容 {max_y} > pet_rect.bottom {rect.bottom()}）"


# --------------------------------------------------------------------------- #
# 姿态集合
# --------------------------------------------------------------------------- #
def _action_poses() -> dict[str, PetPose]:
    poses: dict[str, PetPose] = {}

    press = PetModel()
    press.press_arm()
    press.update(0.033, 1.0)
    press.update(0.033, 1.033)  # 按压峰值附近
    poses["press_arm"] = press.pose()

    drag = PetModel()
    drag.set_dragging(True)
    for i in range(30):
        drag.update(0.033, 1.0 + i * 0.033)
    poses["dragging"] = drag.pose()

    hover = PetModel()
    hover.set_hover(True)
    for i in range(10):
        hover.update(0.033, 1.0 + i * 0.033)
    poses["hover"] = hover.pose()

    return poses


def _named_poses() -> dict[str, PetPose]:
    named: dict[str, PetPose] = {
        f"expr:{e.name}": PetModel.pose_for_expression(e) for e in Expression
    }
    named.update(_action_poses())
    return named


# --------------------------------------------------------------------------- #
# ★ 必验项 1：实际内容 ⊆ pet_rect（8 表情 + 3 动作姿态 × 3 缩放）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scale", _SCALES)
def test_rendered_content_contained_in_pet_rect(qtbot, scale: float, capsys) -> None:
    renderer = PetRenderer()
    rows: list[str] = []
    failures: list[str] = []

    for name, pose in _named_poses().items():
        window = PetWindow(_StubModel(pose), renderer, scale)
        qtbot.addWidget(window)
        window.set_scale(scale)
        rect = window.pet_rect()

        image = _render(renderer, pose, scale)
        bbox = _opaque_bbox(image)
        assert bbox is not None, f"{name}@scale{scale} 渲染为空白"

        contained = (
            rect.left() <= bbox[0]
            and rect.top() <= bbox[1]
            and rect.right() >= bbox[2]
            and rect.bottom() >= bbox[3]
        )
        rows.append(
            f"scale={scale:<3} {name:<18} bbox=({bbox[0]:>3},{bbox[1]:>3},{bbox[2]:>3},{bbox[3]:>3})"
            f"  pet_rect=({rect.left():>3},{rect.top():>3},{rect.right():>3},{rect.bottom():>3})"
            f"  {'OK' if contained else '**CLIP**'}"
        )
        try:
            _assert_contained(bbox, rect, f"{name}@scale{scale}")
        except AssertionError as exc:
            failures.append(str(exc))

    with capsys.disabled():
        print("\n[dirty-rect] " + "\n[dirty-rect] ".join(rows))

    assert not failures, "收窄重绘矩形裁剪了猫：\n" + "\n".join(failures)


# --------------------------------------------------------------------------- #
# ★ 必验项 1b：光晕态（睡觉/兴奋）确实需要"回退整窗"，且确实铺满近乎整窗
# --------------------------------------------------------------------------- #
def test_glow_states_fallback_full_window_and_would_clip_if_narrowed(qtbot, capsys) -> None:
    """睡觉/兴奋态：必须回退整窗，且**收窄矩形确实装不下光晕**（证明回退非多此一举）。"""

    renderer = PetRenderer()
    for expr in (Expression.SLEEPING, Expression.EXCITED):
        pose = PetModel.pose_for_expression(expr)
        assert pose.glow_alpha > PetRenderer.GLOW_ALPHA_EPSILON, (
            f"{expr.name} 应处于光晕态（glow_alpha={pose.glow_alpha}）"
        )
        for scale in _SCALES:
            window = PetWindow(_StubModel(pose), renderer, scale)
            qtbot.addWidget(window)
            window.set_scale(scale)
            rect = window.pet_rect()
            assert rect == window.rect(), f"{expr.name}@scale{scale} 未回退整窗"

            image = _render(renderer, pose, scale)
            bbox = _opaque_bbox(image)
            assert bbox is not None
            w = image.width()
            span_x = (bbox[2] - bbox[0] + 1) / w

            # 收窄矩形（不含光晕）能否装下实际内容？装不下 → 回退整窗是必要且正确的。
            narrowed = PetRenderer.body_bounds(pose, scale)
            narrowed_contains = (
                narrowed.left() <= bbox[0]
                and narrowed.top() <= bbox[1]
                and narrowed.right() >= bbox[2]
                and narrowed.bottom() >= bbox[3]
            )
            with capsys.disabled():
                print(
                    f"[glow] {expr.name}@scale{scale} bbox={bbox} 水平覆盖={span_x:.0%} "
                    f"narrowed=({narrowed.left()},{narrowed.top()},{narrowed.right()},{narrowed.bottom()}) "
                    f"would_clip={not narrowed_contains}"
                )

            # 光晕横向铺满整窗 → 收窄必裁；据此断言回退整窗的必要性
            assert span_x > 0.95, f"{expr.name}@scale{scale} 光晕未铺满整窗宽度（{span_x:.0%}）"
            assert not narrowed_contains, (
                f"{expr.name}@scale{scale} 收窄矩形竟能装下光晕内容，回退整窗存疑"
            )
            _assert_contained(bbox, rect, f"{expr.name}@scale{scale}")


# --------------------------------------------------------------------------- #
# ★ 必验项 1c：glow_alpha 阈值边界两侧逻辑正确且都不裁剪
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "glow,expect_full_window",
    [(0.009, False), (0.010, False), (0.011, True)],
)
def test_glow_alpha_threshold_boundary(qtbot, glow: float, expect_full_window: bool) -> None:
    renderer = PetRenderer()
    assert PetRenderer.GLOW_ALPHA_EPSILON == 0.01
    base = PetModel.pose_for_expression(Expression.HAPPY)
    pose = replace(base, glow_alpha=glow)

    for scale in _SCALES:
        window = PetWindow(_StubModel(pose), renderer, scale)
        qtbot.addWidget(window)
        window.set_scale(scale)
        rect = window.pet_rect()

        is_full = rect == window.rect()
        assert is_full is expect_full_window, (
            f"glow={glow}@scale{scale} 期望 full={expect_full_window} 实际 full={is_full}"
        )

        image = _render(renderer, pose, scale)
        bbox = _opaque_bbox(image)
        assert bbox is not None, f"glow={glow}@scale{scale} 渲染空白"
        _assert_contained(bbox, rect, f"glow={glow}@scale{scale}")


# --------------------------------------------------------------------------- #
# 收窄确实生效（非 no-op）：常规表情 pet_rect 必须严格小于整窗
# --------------------------------------------------------------------------- #
def test_normal_pose_rect_is_actually_narrowed(qtbot) -> None:
    renderer = PetRenderer()
    pose = PetModel.pose_for_expression(Expression.HAPPY)
    for scale in _SCALES:
        window = PetWindow(_StubModel(pose), renderer, scale)
        qtbot.addWidget(window)
        window.set_scale(scale)
        rect = window.pet_rect()
        assert rect != window.rect(), f"scale={scale} 常规态未收窄（FR-35 未生效）"
        assert rect.width() < window.width() or rect.height() < window.height()


def test_body_bounds_within_canvas() -> None:
    for expr in Expression:
        pose = PetModel.pose_for_expression(expr)
        for scale in _SCALES:
            bounds = PetRenderer.body_bounds(pose, scale)
            assert bounds.left() >= 0 and bounds.top() >= 0
            assert bounds.right() < int(round(C.BASE_W * scale))
            assert bounds.bottom() < int(round(C.BASE_H * scale))
