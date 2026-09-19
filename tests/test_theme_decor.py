"""主题造型装饰回归测试（阶段 D：造型元素增强）。

覆盖：

- ``THEME_DECOR`` 结构：键集合 == 7 套皮肤；色值合法 ``#RRGGBB``；取值在白名单内；
  ``default`` 全空（品牌基准形态不得被装饰污染）。
- ``decor_for_theme``：未知名称回落 ``default`` 且不抛异常；各皮肤返回**各自**的装饰
  （字面量期望，防「全部回落 default」的假实现）。
- ``PetRenderer``：``has_decor()`` 随 ``set_theme`` 正确翻转；装饰粒子位置是
  ``(decor, phase)`` 的**纯函数**（同相位必同坐标、异相位必不同）。
- ``paint()``：7 套皮肤带装饰渲染跑通；**装饰确实被画出来**（关掉装饰后逐像素哈希改变）；
  粒子随相位移动（同一皮肤、同一姿态、不同相位 → 图像不同）。
- ``PetWindow.pet_rect()``：带装饰时回退整窗（否则粒子会被脏区收窄裁掉）。

纪律：期望值一律写**字面量**（不引用被测常量自身拼期望）；每条新增断言均经变异验证。
"""

from __future__ import annotations

import hashlib

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel
from desktop_pet.core.theme import decor_for_theme
from desktop_pet.ui.pet_renderer import PetRenderer
from desktop_pet.ui.pet_window import PetWindow

_ALL_THEMES = (
    "default", "spring", "summer", "autumn", "winter",
    "spring_festival", "christmas",
)


def _image_hash(image: QImage) -> str:
    """图像内容的 MD5（用于「装饰画没画出来」的逐像素对比）。"""

    return hashlib.md5(bytes(image.constBits())).hexdigest()


def _opaque_pixel_count(image: QImage) -> int:
    """非透明像素数。"""

    total = 0
    for y in range(image.height()):
        for x in range(image.width()):
            if image.pixel(x, y) & 0xFF000000:
                total += 1
    return total


def _render(renderer: PetRenderer, pose, scale: float = 1.0) -> QImage:
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


def _make_window(qtbot, theme: str) -> PetWindow:
    window = PetWindow(PetModel(), PetRenderer(), 1.0)
    qtbot.addWidget(window)
    window._renderer.set_theme(theme)
    window.show()
    return window


# --------------------------------------------------------------------------- #
# 1. THEME_DECOR 数据契约（字面量期望）
# --------------------------------------------------------------------------- #
def test_theme_decor_keys_match_themes() -> None:
    """装饰表与皮肤表**键集合一致**（每套皮肤都必须有装饰描述，含全空的 default）。"""

    assert set(C.THEME_DECOR) == {
        "default", "spring", "summer", "autumn", "winter",
        "spring_festival", "christmas",
    }


def test_theme_decor_default_is_all_empty() -> None:
    """``default`` 必须全空：品牌基准形态不得被装饰污染。"""

    expected = C.ThemeDecor(
        particle="none", particle_color="#FFFFFF", particle_count=0,
        backdrop="none", backdrop_color="#FFFFFF",
        accessory="none", accessory_color="#FFFFFF", accessory_accent="#FFFFFF",
    )
    assert C.THEME_DECOR["default"] == expected


def test_theme_decor_christmas_literal_values() -> None:
    """圣诞 = 雪花 + 圣诞帽（字面量全等，防静默漂移）。"""

    expected = C.ThemeDecor(
        particle="snow", particle_color="#F2F8FF", particle_count=10,
        backdrop="none", backdrop_color="#FFFFFF",
        accessory="santa_hat", accessory_color="#E4574F", accessory_accent="#FFFFFF",
    )
    assert C.THEME_DECOR["christmas"] == expected


def test_theme_decor_spring_literal_values() -> None:
    """春 = 垂柳布景 + 花瓣 + 小花（字面量全等）。"""

    expected = C.ThemeDecor(
        particle="petal", particle_color="#FFC9DA", particle_count=6,
        backdrop="willow", backdrop_color="#8FCB79",
        accessory="flower", accessory_color="#FF9EC4", accessory_accent="#FFF3B0",
    )
    assert C.THEME_DECOR["spring"] == expected


@pytest.mark.parametrize("name", _ALL_THEMES)
def test_theme_decor_colors_are_valid_hex(name: str) -> None:
    """每套皮肤的 4 个色值均为合法大写 ``#RRGGBB``。"""

    d = C.THEME_DECOR[name]
    for hexv in (
        d.particle_color, d.backdrop_color, d.accessory_color, d.accessory_accent,
    ):
        assert isinstance(hexv, str) and len(hexv) == 7 and hexv.startswith("#")
        int(hexv[1:], 16)  # 非法 hex 会抛 ValueError → 测试失败
        assert hexv == hexv.upper()


@pytest.mark.parametrize("name", _ALL_THEMES)
def test_theme_decor_values_within_allowed_sets(name: str) -> None:
    """粒子 / 布景 / 配件取值都在白名单内，粒子数量在 0..16。"""

    d = C.THEME_DECOR[name]
    assert d.particle in C.THEME_DECOR_PARTICLES
    assert d.backdrop in C.THEME_DECOR_BACKDROPS
    assert d.accessory in C.THEME_DECOR_ACCESSORIES
    assert 0 <= d.particle_count <= 16
    if d.particle == "none":
        assert d.particle_count == 0, "粒子形状为 none 时数量必须为 0"


def test_theme_decor_registered_in_all() -> None:
    for name in (
        "ThemeDecor", "THEME_DECOR", "THEME_DECOR_PARTICLES",
        "THEME_DECOR_BACKDROPS", "THEME_DECOR_ACCESSORIES",
    ):
        assert name in C.__all__, f"{name} 未登记进 constants.__all__"
    assert "decor_for_theme" in __import__(
        "desktop_pet.core.theme", fromlist=["__all__"]
    ).__all__


# --------------------------------------------------------------------------- #
# 2. decor_for_theme 纯函数
# --------------------------------------------------------------------------- #
def test_decor_for_theme_unknown_falls_back_to_default() -> None:
    """未知名称回落 ``default``（= 全空装饰），**不抛异常**。"""

    expected = C.ThemeDecor(
        particle="none", particle_color="#FFFFFF", particle_count=0,
        backdrop="none", backdrop_color="#FFFFFF",
        accessory="none", accessory_color="#FFFFFF", accessory_accent="#FFFFFF",
    )
    assert decor_for_theme("banana") == expected
    assert decor_for_theme("") == expected
    assert decor_for_theme(None) == expected  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "name,field,expected",
    [
        ("winter", "particle", "snow"),
        ("winter", "accessory", "scarf"),
        ("christmas", "accessory", "santa_hat"),
        ("spring", "backdrop", "willow"),
        ("autumn", "particle", "leaf"),
        ("summer", "particle", "bubble"),
        ("spring_festival", "accessory", "lantern"),
    ],
)
def test_decor_for_theme_returns_specific_decor(
    name: str, field: str, expected: str,
) -> None:
    """各皮肤返回**各自**的装饰（防「全部回落 default」的假实现）。"""

    assert getattr(decor_for_theme(name), field) == expected


# --------------------------------------------------------------------------- #
# 3. PetRenderer：has_decor / 粒子确定性
# --------------------------------------------------------------------------- #
def test_renderer_has_decor_follows_theme() -> None:
    renderer = PetRenderer()
    assert renderer.has_decor() is False, "default 不应带装饰"

    for name in ("christmas", "spring", "winter", "autumn", "summer", "spring_festival"):
        renderer.set_theme(name)
        assert renderer.has_decor() is True, f"{name} 应带装饰"

    renderer.set_theme("default")
    assert renderer.has_decor() is False
    renderer.set_theme("banana")  # 非法名回落 default
    assert renderer.has_decor() is False


def test_decor_particles_are_deterministic() -> None:
    """粒子位置是 ``(decor, phase)`` 的**纯函数**：同相位必同坐标（禁运行期 random）。"""

    renderer = PetRenderer()
    renderer.set_theme("christmas")
    a = renderer.decor_particle_positions(phase=12.5)
    b = renderer.decor_particle_positions(phase=12.5)
    assert a == b
    assert a != ()
    assert len(a) == 10, "christmas 粒子数字面量为 10"

    c = renderer.decor_particle_positions(phase=13.5)
    assert a != c, "相位推进后粒子应当移动（否则动画失效）"


def test_decor_particles_no_particles_for_default() -> None:
    renderer = PetRenderer()
    renderer.set_theme("default")
    assert renderer.decor_particle_positions(phase=1.0) == ()


@pytest.mark.parametrize("name", ("christmas", "spring", "autumn", "summer"))
def test_decor_particles_stay_near_canvas(name: str) -> None:
    """粒子坐标始终贴近画布（含回绕缓冲），不得飞出画面。"""

    renderer = PetRenderer()
    renderer.set_theme(name)
    for phase in (0.0, 3.7, 61.0, 1000.0, 86400.0):
        for x, y, size in renderer.decor_particle_positions(phase=phase):
            assert -10.0 <= x <= 170.0, f"{name} phase={phase} x={x}"
            # y 落域 = [-回绕缓冲, 画布高 + 回绕缓冲) = [-12, 192)
            assert -12.0 <= y < 192.0, f"{name} phase={phase} y={y}"
            assert 0.5 <= size <= 1.6


# --------------------------------------------------------------------------- #
# 4. paint()：装饰真的被画出来 + 随相位移动
# --------------------------------------------------------------------------- #
def test_paint_with_decor_differs_from_no_decor() -> None:
    """同一皮肤同一姿态同一相位，关掉装饰后逐像素哈希必须改变（装饰确实在画）。"""

    pose = PetModel.pose_for_expression(Expression.HAPPY)
    renderer = PetRenderer()
    renderer.set_theme("christmas")
    renderer.set_decor_phase(7.0)
    with_decor = _image_hash(_render(renderer, pose))

    # 仅关掉装饰（其余一切不变）→ 图像必须不同
    renderer._decor = C.THEME_DECOR["default"]
    without_decor = _image_hash(_render(renderer, pose))
    assert with_decor != without_decor, "关掉装饰后图像未变 → 装饰没有被绘制"


def test_paint_decor_opaque_pixel_count_increases() -> None:
    """装饰会净增非透明像素（粒子/配件不是画在既有像素上的不可见层）。"""

    pose = PetModel.pose_for_expression(Expression.HAPPY)
    renderer = PetRenderer()
    renderer.set_theme("winter")
    renderer.set_decor_phase(3.0)
    with_count = _opaque_pixel_count(_render(renderer, pose))
    renderer._decor = C.THEME_DECOR["default"]
    without_count = _opaque_pixel_count(_render(renderer, pose))
    assert with_count > without_count


def test_paint_decor_moves_with_phase() -> None:
    """同一皮肤同一姿态、不同相位 → 图像不同（粒子动画生效）。"""

    pose = PetModel.pose_for_expression(Expression.HAPPY)
    renderer = PetRenderer()
    renderer.set_theme("autumn")
    renderer.set_decor_phase(0.0)
    early = _image_hash(_render(renderer, pose))
    renderer.set_decor_phase(4.0)
    later = _image_hash(_render(renderer, pose))
    assert early != later, "相位推进后图像未变 → 粒子动画失效"


@pytest.mark.parametrize("name", _ALL_THEMES)
def test_paint_all_themes_with_decor_no_exception(name: str) -> None:
    """7 套皮肤带装饰渲染跑通（含 default 全空路径）。"""

    pose = PetModel.pose_for_expression(Expression.SLEEPING)  # 顺带覆盖光晕整窗路径
    renderer = PetRenderer()
    renderer.set_theme(name)
    renderer.set_decor_phase(2.5)
    image = _render(renderer, pose, scale=1.2)
    assert not image.isNull(), f"{name} 带装饰渲染失败"


# --------------------------------------------------------------------------- #
# 5. 脏区：带装饰必须回退整窗（否则粒子被收窄矩形裁掉）
# --------------------------------------------------------------------------- #
def test_pet_rect_falls_back_to_full_window_with_decor(qtbot) -> None:
    window = _make_window(qtbot, "christmas")
    assert window._renderer.has_decor() is True
    assert window.pet_rect() == window.rect(), "带装饰时应回退整窗，避免粒子被裁切"

    window._renderer.set_theme("default")
    narrowed = window.pet_rect()
    assert narrowed != window.rect(), "default 无装饰时不应整窗重绘（性能回退）"
    assert window.rect().contains(narrowed)
