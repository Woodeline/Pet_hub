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
