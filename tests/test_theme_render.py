"""主题解析与应用链路回归测试（阶段 A3）。

**数据级断言为主**（v1.1 P4）：offscreen 下逐像素对比渐变既慢又脆，因此主断言落在
「纯函数解析结果」「停靠点数据」「取色数值」上，``paint()`` 只做**跑通不抛异常**的冒烟。

覆盖：

- ``resolve_theme`` 逐月字面量期望 + 手动覆盖 ``auto`` + 非法回落。
- ``theme_stops`` 未知名称回落 ``default`` 且不抛异常。
- 7 套皮肤停靠点两两不同；``_sample_gradient`` 同一 ``frac`` 在不同皮肤下取色不同。
- ``paint()`` 遍历 7 套皮肤 offscreen 跑通（冒烟）。
- ``PetPose`` 所有 dataclass 字段类型均为 ``float``（防 R1 复发：主题绝不可进姿态通道）。
"""

from __future__ import annotations

from dataclasses import fields

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel, PetPose
from desktop_pet.core.theme import resolve_theme, theme_stops
from desktop_pet.ui.pet_renderer import PetRenderer

_ALL_THEMES = (
    "default", "spring", "summer", "autumn", "winter",
    "spring_festival", "christmas",
)


# --------------------------------------------------------------------------- #
# 1. resolve_theme 纯函数（字面量期望）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "month,expected",
    [
        (1, "winter"), (2, "winter"), (3, "spring"), (4, "spring"),
        (5, "spring"), (6, "summer"), (7, "summer"), (8, "summer"),
        (9, "autumn"), (10, "autumn"), (11, "autumn"), (12, "winter"),
    ],
)
def test_resolve_theme_auto_all_months(month: int, expected: str) -> None:
    """``auto`` 档逐月（1..12）字面量期望。"""

    assert resolve_theme(month, C.AUTO_THEME) == expected


def test_resolve_theme_manual_overrides_auto() -> None:
    """手动选择覆盖 ``auto``：即使月份指向 winter，选 ``christmas`` 也返回 christmas。"""

    assert resolve_theme(1, "christmas") == "christmas"
    assert resolve_theme(6, "christmas") == "christmas"
    assert resolve_theme(6, "winter") == "winter"


@pytest.mark.parametrize(
    "month,user,expected",
    [
        (0, C.AUTO_THEME, "default"),     # 月份越界（下界）
        (13, C.AUTO_THEME, "default"),    # 月份越界（上界）
        (-1, C.AUTO_THEME, "default"),
        (99, C.AUTO_THEME, "default"),
        (6, "banana", "default"),         # 非法皮肤名 → 回落默认
        (6, "", "default"),
        (6, "AUTO", "default"),           # 大小写敏感：非法
    ],
)
def test_resolve_theme_illegal_falls_back(month: int, user: str, expected: str) -> None:
    """越界月份 / 非法取值一律回落 ``default``（防御性，不抛异常）。"""

    assert resolve_theme(month, user) == expected


def test_resolve_theme_bad_month_type_falls_back() -> None:
    """月份类型不可解析（``None``）→ 回落 ``default``（不抛异常）。"""

    assert resolve_theme(None, C.AUTO_THEME) == "default"  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 2. theme_stops
# --------------------------------------------------------------------------- #
def test_theme_stops_known_names_return_data() -> None:
    """已知名称返回其停靠点，且恰为 5 个。"""

    for name in _ALL_THEMES:
        stops = theme_stops(name)
        assert stops == C.THEMES[name]
        assert len(stops) == 5
        assert stops is C.THEMES[name]  # 同一对象，非拷贝


def test_theme_stops_unknown_falls_back_to_default() -> None:
    """未知名称回落 ``default`` 且**不抛异常**。"""

    assert theme_stops("banana") is C.THEMES["default"]
    assert theme_stops("") is C.THEMES["default"]


# --------------------------------------------------------------------------- #
# 3. 停靠点互不相同 + 取色随皮肤变化
# --------------------------------------------------------------------------- #
def test_theme_stops_pairwise_distinct() -> None:
    """7 套皮肤停靠点序列两两不同。"""

    seqs = [theme_stops(name) for name in _ALL_THEMES]
    assert len(set(seqs)) == len(seqs)


@pytest.mark.parametrize("frac", [0.0, 0.25, 0.5, 0.75, 1.0])
def test_sample_gradient_differs_across_themes(frac: float) -> None:
    """同一 ``frac`` 在默认皮肤与各皮肤下取样 → 颜色互不相同。"""

    default_renderer = PetRenderer()
    default_renderer.set_theme("default")
    baseline = default_renderer._sample_gradient(frac)

    for name in _ALL_THEMES:
        if name == "default":
            continue
        renderer = PetRenderer()
        renderer.set_theme(name)
        sampled = renderer._sample_gradient(frac)
        assert sampled.startswith("#") and len(sampled) == 7, f"{name}@{frac} 非法色值"
        assert sampled != baseline, f"{name}@{frac} 与默认皮肤取色相同：{sampled}"


def test_renderer_set_theme_unknown_falls_back() -> None:
    """``set_theme`` 未知名回落默认皮肤（不抛异常）。"""

    renderer = PetRenderer()
    renderer.set_theme("banana")
    assert renderer.theme_stops() is C.THEMES["default"]


def test_renderer_default_theme_is_default() -> None:
    """构造后默认皮肤为 ``default``。"""

    assert PetRenderer().theme_stops() is C.THEMES["default"]


# --------------------------------------------------------------------------- #
# 4. paint() 遍历 7 套皮肤（冒烟）
# --------------------------------------------------------------------------- #
def _render(renderer: PetRenderer, pose: PetPose, scale: float = 1.0) -> QImage:
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


def test_paint_all_themes_no_exception(qtbot) -> None:
    """遍历 7 套皮肤 + 各画一帧，均不抛异常且产生非空图像。"""

    renderer = PetRenderer()
    pose = PetModel.pose_for_expression(Expression.HAPPY)
    for name in _ALL_THEMES:
        renderer.set_theme(name)
        image = _render(renderer, pose)
        assert not image.isNull(), f"{name} 渲染失败"


def test_paint_glow_themes_no_exception(qtbot) -> None:
    """带光晕的姿态（睡觉 / 兴奋）在各皮肤下也不抛异常（覆盖 ``_draw_glow`` 取色分支）。"""

    renderer = PetRenderer()
    for name in _ALL_THEMES:
        renderer.set_theme(name)
        _render(renderer, PetModel.pose_for_expression(Expression.SLEEPING))
        _render(renderer, PetModel.pose_for_expression(Expression.EXCITED))


# --------------------------------------------------------------------------- #
# 5. R1 防复发：PetPose 全字段为 float
# --------------------------------------------------------------------------- #
def test_petpose_fields_are_all_float() -> None:
    """``PetPose`` 每个 dataclass 字段的类型注解都必须是 ``float``。

    防 R1 复发：若有人给 ``PetPose`` 加了 ``theme: str`` 之类非 float 字段，
    ``lerp_to`` 会在首帧 ``TypeError``。这里从**类型注解**层面直接拦截。
    """

    for f in fields(PetPose):
        assert f.type == "float", f"PetPose.{f.name} 类型为 {f.type!r}，必须为 float"


def test_petpose_instance_values_are_all_float() -> None:
    """实例化后的每个字段值也必须是 ``float``。"""

    pose = PetModel.pose_for_expression(Expression.EXCITED)
    for f in fields(PetPose):
        assert isinstance(getattr(pose, f.name), float), f"{f.name} 不是 float"
