"""ui.confirm_dialog —— 主题化二次确认对话框（替代 ``QMessageBox.question``）。

背景（界面统一方案 §2 E1 / §5 T4）：生词本「清空」原走 ``QMessageBox.question``，
完全未接主题 —— 系统方角 + 系统色 + DWM 原生阴影，与其余主题化窗口格格不入。
本模块提供 :class:`ConfirmDialog`：token 配色（随主题 / 点缀色走）、圆角 / 间距 / 字号
全走 ``core.constants``，并以 ``ghost``（取消）+ ``destructive``（确认）区分主次操作。

形态约定（对齐方案决策点 D3「暂不做窗口 chrome」）：
- **不设** ``Qt.FramelessWindowHint``：与其它业务窗口同属「系统标题栏窗口」族；
- **不做**自绘阴影：窗口已有 DWM 原生阴影，叠加易过重（本批次统一不引入任何自绘阴影）。

用法::

    if ConfirmDialog.ask(self, title, text, confirm_text="清空…"):
        ...  # 用户确认后执行
"""

from __future__ import annotations

from typing import Final

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.ui import theme

#: 「取消」按钮文案（与 ui.bubble_text_dialog 的取消按钮一致：中文界面固定文案）。
_CANCEL_TEXT: Final[str] = "取消"


class ConfirmDialog(QDialog):
    """主题化二次确认对话框（模态）。

    Args:
        title: 对话框标题（``setWindowTitle`` 与标题 label 共用）。
        text: 正文说明（自动换行）。
        confirm_text: 确认按钮文案（如「清空…」）。
        parent: Qt 父对象（通常传业务窗口）。
    """

    def __init__(
        self,
        title: str,
        text: str,
        confirm_text: str,
        parent: QWidget | None = None,
    ) -> None:
        """按 token 配色与四档圆角语义构建对话框，并接线取消 / 确认。"""

        super().__init__(parent)
        self.setWindowTitle(title)
        # token 配色随主题 / 点缀色走（与非对话框窗口同源）。
        theme.apply_theme(self)

        c = C.SEMANTIC_COLORS
        sp = C.SPACING
        fs = C.FONT_SIZE

        root = QVBoxLayout(self)
        root.setContentsMargins(sp["lg"], sp["lg"], sp["lg"], sp["lg"])
        root.setSpacing(sp["md"])

        # 标题：面板档大字（title 字号 + text_primary + 加粗）
        title_label = QLabel(title, self)
        title_label.setWordWrap(True)
        title_label.setStyleSheet(
            f"font-size: {fs['title']}px; font-weight: bold;"
            f" color: {c['text_primary']}; background: transparent;"
        )
        root.addWidget(title_label)

        # 正文：次级色 + 自动换行
        text_label = QLabel(text, self)
        text_label.setWordWrap(True)
        text_label.setStyleSheet(
            f"color: {c['text_secondary']}; background: transparent;"
        )
        root.addWidget(text_label)

        # 底栏：右对齐 [取消][确认]
        buttons = QHBoxLayout()
        buttons.addStretch(1)

        self._cancel_btn = QPushButton(_CANCEL_TEXT, self)
        theme.set_variant(self._cancel_btn, "ghost")
        self._cancel_btn.clicked.connect(self.reject)
        buttons.addWidget(self._cancel_btn)

        self._confirm_btn = QPushButton(confirm_text, self)
        theme.set_variant(self._confirm_btn, "destructive")
        self._confirm_btn.setDefault(True)
        self._confirm_btn.clicked.connect(self.accept)
        buttons.addWidget(self._confirm_btn)

        root.addLayout(buttons)

    @staticmethod
    def ask(
        parent: QWidget | None,
        title: str,
        text: str,
        confirm_text: str,
    ) -> bool:
        """便捷入口：弹出模态确认框，返回用户是否确认（``Accepted``）。"""

        dialog = ConfirmDialog(title, text, confirm_text, parent)
        return dialog.exec() == QDialog.DialogCode.Accepted


__all__ = ["ConfirmDialog"]
