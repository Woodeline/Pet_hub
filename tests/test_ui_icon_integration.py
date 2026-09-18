"""图标工厂接入窗口的集成回归（P1：``icon_factory`` → 按钮 ``setIcon``）。

守护目标：详情窗口与生词本窗口的关键按钮**确实**挂上了程序化矢量图标——
``icon()`` 非空、``availableSizes()`` 非空、并能按按钮图标尺寸渲染出非空位图，
而不是「只构造了按钮、根本没接线」的假实现。

注：图标像素尺寸期望值刻意写成**字面量 16**（而非引用 ``C.SPACING["lg"]``），
避免「期望值与被测代码共用同一常量」导致的自引用假绿；生产侧如需改尺寸，
本测试会如实失败以提醒同步更新期望。
"""

from __future__ import annotations

from PySide6.QtWidgets import QPushButton

from desktop_pet.ui.vocab_window import VocabWindow
from desktop_pet.ui.word_detail_window import WordDetailWindow

#: 生产侧应使用的按钮图标像素尺寸（当前 = ``C.SPACING["lg"]`` = 16）。
_EXPECTED_ICON_PX = 16


def _assert_button_has_rendered_icon(button: QPushButton) -> None:
    """断言按钮挂着可渲染的图标（非空 + 有尺寸 + 能画出非空位图）。"""

    icon = button.icon()
    assert not icon.isNull(), f"按钮「{button.text()}」未挂图标"

    sizes = icon.availableSizes()
    assert sizes, f"按钮「{button.text()}」图标无可用尺寸（availableSizes 为空）"
    assert all(s.width() > 0 and s.height() > 0 for s in sizes), (
        f"按钮「{button.text()}」图标尺寸非法：{sizes}"
    )

    rendered = icon.pixmap(_EXPECTED_ICON_PX, _EXPECTED_ICON_PX)
    assert not rendered.isNull(), f"按钮「{button.text()}」图标无法渲染出位图"


def _assert_icon_size(button: QPushButton) -> None:
    """断言按钮图标尺寸 == 预期像素（字面量，避免自引用）。"""

    size = button.iconSize()
    assert size.width() == _EXPECTED_ICON_PX and size.height() == _EXPECTED_ICON_PX, (
        f"按钮「{button.text()}」图标尺寸应为 {_EXPECTED_ICON_PX}px，"
        f"实际 {size.width()}x{size.height()}"
    )


def test_word_detail_buttons_have_icons(qtbot) -> None:
    """详情窗口「重试 / 关闭」按钮必须挂图标（文案不变）。"""

    window = WordDetailWindow()
    qtbot.addWidget(window)

    _assert_button_has_rendered_icon(window._retry_btn)
    _assert_button_has_rendered_icon(window._close_btn)
    _assert_icon_size(window._retry_btn)
    _assert_icon_size(window._close_btn)


def test_vocab_buttons_have_icons(qtbot) -> None:
    """生词本窗口「移除 / 清空 / 关闭」按钮必须挂图标（文案不变）。"""

    window = VocabWindow()
    qtbot.addWidget(window)

    for button in (window._btn_remove, window._btn_clear, window._btn_close):
        _assert_button_has_rendered_icon(button)
        _assert_icon_size(button)
