"""B 版气泡质感重构冒烟（新常量 / 等级 chip / 无图片 / 尺寸不变 / 按钮微交互）。"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QImage, QPainter

from desktop_pet.core import constants as C
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.ui.bubble import BubbleWindow
from desktop_pet.ui.bubble_button_bar import BubbleButtonBar


def _entry() -> VocabEntry:
    return VocabEntry(
        id="n5-0001", level="N5", word="食べる", kana="たべる",
        translation="吃", meaning="进食", romaji="taberu",
    )


def test_word_level_is_recorded(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)
    assert bubble._line_level == "N5"
    bubble.hide_bubble()


def test_new_palette_constants_exist() -> None:
    for key in (
        "bubble_shadow",
        "bubble_divider",
        "bubble_gradient_bottom",
        "jp_level_chip_bg",
        "jp_level_chip_text",
    ):
        assert key in C.COLORS, f"缺少气泡质感配色常量：{key}"


def test_paint_helpers_exist() -> None:
    bubble = BubbleWindow()
    assert callable(bubble._paint_shadow)
    assert callable(bubble._paint_divider)
    assert callable(bubble._paint_level_chip)


def test_base_size_unchanged() -> None:
    assert C.BASE_W == 160
    assert C.BASE_H == 180


def test_word_bubble_renders_without_crash(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_word(_entry(), 30.0)
    bubble._alpha = 1.0

    image = QImage(bubble.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    bubble.render(painter, QPoint(0, 0))  # 触发 paintEvent（阴影 / 渐变 / 分割线 / 等级 chip）
    painter.end()

    bubble.hide_bubble()


def test_button_bar_keeps_no_input_transparency(qtbot) -> None:
    """按钮条「不含穿透标志」断言仍绿（B 版微交互不引入穿透）。"""

    bar = BubbleButtonBar()
    qtbot.addWidget(bar)
    assert Qt.WindowType.WindowTransparentForInput not in bar.windowFlags()
    assert bar.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) is False
    assert bar._btn_mastered.graphicsEffect() is not None  # 轻投影已挂载


# --------------------------------------------------------------------------- #
# 双层描边（贴纸风）：白晕外环 + 深棕内线，浅色/深色背景均清晰
# --------------------------------------------------------------------------- #
def _render_bubble_image(qtbot) -> QImage:
    """渲染一个满 alpha 的情绪气泡（pointing_down），返回离屏 QImage。"""

    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_message("测试气泡", 3.0)
    bubble._alpha = 1.0
    image = QImage(bubble.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    bubble.render(painter, QPoint(0, 0))
    painter.end()
    bubble.hide_bubble()
    return image


def _luminance(color) -> float:
    return 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()


def test_double_stroke_halo_and_border_pixels(qtbot) -> None:
    """白晕与淡灰细描边真实落在像素上：内线淡色、外环近白（细线贴纸风改版）。"""

    from PySide6.QtGui import QColor

    assert QColor(C.COLORS["bubble_border"]).isValid()
    image = _render_bubble_image(qtbot)
    mid_y = image.height() // 2

    border = image.pixelColor(C.BUBBLE_STROKE_MARGIN, mid_y)      # 路径边缘 = 内线中心
    halo = image.pixelColor(C.BUBBLE_STROKE_MARGIN - 2, mid_y)    # 内线之外 = 白晕环

    # 内层描边：淡灰细线（亮度明显高于旧深棕契约，但仍与纯白填充有差）
    assert border.alpha() > 200
    assert 180 <= _luminance(border) <= 246
    # 外层白晕：近白、且确实有覆盖（半透明）
    assert halo.alpha() >= 120
    assert min(halo.red(), halo.green(), halo.blue()) >= 220


def test_edge_contrast_on_dark_and_light_backdrops(qtbot) -> None:
    """把气泡合成到深灰/浅米两种「壁纸」上：深底靠白晕分离，浅底靠白晕微分离 +
    淡灰细线轻勾边（改版后不再使用深描边，浅底契约从「对比 ≥60」放宽）。"""

    from PySide6.QtGui import QColor

    image = _render_bubble_image(qtbot)
    mid_y = image.height() // 2
    border_x = C.BUBBLE_STROKE_MARGIN
    halo_x = C.BUBBLE_STROKE_MARGIN - 2

    for backdrop, expect in (
        ("#20242C", "halo"),   # 深色壁纸 → 白晕提供边缘对比
        ("#F5EFE2", "light"),  # 浅色壁纸 → 白晕微分离 + 淡描边轻勾边
    ):
        canvas = QImage(image.size(), QImage.Format.Format_ARGB32)
        canvas.fill(QColor(backdrop))
        painter = QPainter(canvas)
        painter.drawImage(0, 0, image)
        painter.end()

        bg_lum = _luminance(QColor(backdrop))
        halo_lum = _luminance(canvas.pixelColor(halo_x, mid_y))
        if expect == "halo":
            assert halo_lum - bg_lum >= 60, f"深色背景白晕对比不足：{halo_lum} vs {bg_lum}"
        else:
            # 描边带（边缘 ±3px）内存在一条比白晕暗的细线（线存在），且整体仍是
            # 淡色（不再回到深描边契约）。
            band = [
                _luminance(canvas.pixelColor(x, mid_y))
                for x in range(int(border_x) - 3, int(border_x) + 4)
            ]
            edge = min(band)
            assert halo_lum - bg_lum >= 8, f"浅色背景白晕分离不足：{halo_lum} vs {bg_lum}"
            assert halo_lum - edge >= 8, f"细描边可见度不足：{edge} vs {halo_lum}"
            assert edge >= 180, f"描边过深（失去「淡描边」契约）：{edge}"
