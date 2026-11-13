"""ui.window_chrome —— 业务窗口统一视觉外框（标题带 + token 化内边距）。

菜单重设计的设计语言向窗口族落地：每个业务窗口顶部一条统一的
「语义图标 + 加粗标题 + 次级说明」标题带，根布局内边距 / 间距统一取
token 值——消除各窗口 Qt 默认内边距、无身份区的参差观感。

平台边界（沿用方案决策 D3「暂不做窗口 chrome」）：不改系统标题栏、
不自绘窗口阴影；标题带只负责窗口内部的身份与层级，与右键菜单头部
身份区同一设计语言（语义图标 / 次级说明 / token 字号）。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.ui import icon_factory, theme


class WindowHeader(QWidget):
    """窗口标题带：语义图标（可选）+ 加粗标题 + 次级说明。"""

    def __init__(
        self,
        title: str,
        caption: str = "",
        icon: str | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # 标题带高度恒等于 sizeHint：窗口再高也不被根布局拉伸，
        # 否则内部标题/说明会被撑开成大缝隙（2026-11-12 布局缺陷）。
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(C.SPACING["sm"])
        if icon:
            badge = QLabel(self)
            badge.setPixmap(
                icon_factory.menu_icon_pixmap(
                    icon, C.SEMANTIC_COLORS["text_secondary"], 18
                )
            )
            badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            row.addWidget(badge)
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        title_label = QLabel(title, self)
        title_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        theme.set_role(title_label, "window_title")
        box.addWidget(title_label)
        if caption:
            cap = QLabel(caption, self)
            cap.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            theme.set_role(cap, "caption")
            box.addWidget(cap)
        row.addLayout(box, 1)


def polish_root(layout: QLayout) -> None:
    """根布局统一内边距 / 间距：左右 lg、上下 md、间距 md。"""

    layout.setContentsMargins(
        C.SPACING["lg"], C.SPACING["md"], C.SPACING["lg"], C.SPACING["md"]
    )
    layout.setSpacing(C.SPACING["md"])


__all__ = ["WindowHeader", "polish_root"]