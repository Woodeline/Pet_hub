"""ui.data_window —— 「数据管理」窗口（导出 Anki/CSV、一键备份与还原）。

仅负责展示与发信号，**不做文件 IO / 业务判定**（数据目录、对话框、写入、
确认流程全部在 ``app/controller``）。布局：四张动作卡（2×2 网格）+ 数据目录展示。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.ui import icon_factory, motion_ui, theme

logger = logging.getLogger(__name__)


class DataWindow(QWidget):
    """数据管理窗口（普通顶层窗口，纯信号源）。"""

    anki_export_requested = Signal()
    csv_export_requested = Signal()
    backup_export_requested = Signal()
    backup_import_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造数据管理窗口。"""

        super().__init__(parent)
        self.setWindowTitle(C.DATA_WINDOW_TITLE)
        self.resize(C.DATA_WINDOW_W, C.DATA_WINDOW_H)
        self._reduce_motion: bool = False

        self._build_ui()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def set_data_dir(self, path: str) -> None:
        """展示数据目录路径（controller 打开窗口时喂入）。"""

        self._path_label.setText(f"{C.DATA_PATH_LABEL}{path}")

    def set_reduce_motion(self, flag: bool) -> None:
        """注入「减少动效」开关（由 controller 在窗口显示前调用）。"""

        self._reduce_motion = bool(flag)

    def set_accent(self, accent: str | None) -> None:
        """应用主题点缀色（controller 在窗口创建与换肤时调用）。"""

        theme.apply_theme(self, accent)

    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """关闭：开启动效且窗口可见时先淡出再隐藏（与学习记录窗口一致）。"""

        if motion_ui.motion_enabled(self._reduce_motion) and self.isVisible():
            event.ignore()
            motion = motion_ui.create_window_motion(self, self._reduce_motion)
            motion.fade_out(on_finished=self.hide)
            return
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """构建界面元素与布局。"""

        theme.apply_theme(self)
        root = QVBoxLayout(self)
        root.setSpacing(C.SPACING["sm"])

        grid = QGridLayout()
        grid.setSpacing(C.SPACING["sm"])
        cards = (
            ("anki", C.DATA_BTN_ANKI, C.DATA_ANKI_TIP, self.anki_export_requested),
            ("csv", C.DATA_BTN_CSV, C.DATA_CSV_TIP, self.csv_export_requested),
            ("backup", C.DATA_BTN_BACKUP, C.DATA_BACKUP_TIP, self.backup_export_requested),
            ("restore", C.DATA_BTN_RESTORE, C.DATA_RESTORE_TIP, self.backup_import_requested),
        )
        for index, (key, text, tip, signal) in enumerate(cards):
            card = self._build_action_card(key, text, tip, signal)
            grid.addWidget(card, index // 2, index % 2)
        root.addLayout(grid, 1)

        self._path_label = QLabel("", self)
        self._path_label.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_faint']};"
            f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
        )
        self._path_label.setWordWrap(True)
        root.addWidget(self._path_label)

        # 底栏：关闭（与学习记录窗口底栏结构对齐）
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self._btn_close = QPushButton(C.STATS_BTN_CLOSE, self)
        theme.set_variant(self._btn_close, "ghost")
        self._btn_close.setIcon(
            icon_factory.make_icon("close", color=C.SEMANTIC_COLORS["text_primary"])
        )
        self._btn_close.setIconSize(QSize(C.SPACING["lg"], C.SPACING["lg"]))
        self._btn_close.clicked.connect(self.close)
        bottom.addWidget(self._btn_close)
        root.addLayout(bottom)

    def _build_action_card(
        self, key: str, text: str, tip: str, signal: Signal
    ) -> QFrame:
        """构建一张动作卡：图标 + 主按钮 + 说明文字。"""

        card = QFrame(self)
        card.setToolTip(tip)
        card.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        theme.set_role(card, "card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(C.SPACING["md"], C.SPACING["sm"], C.SPACING["md"], C.SPACING["sm"])
        layout.setSpacing(C.SPACING["xs"])

        button = QPushButton(text, card)
        button.clicked.connect(signal.emit)
        layout.addWidget(button)

        desc = QLabel(tip, card)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_secondary']};"
            f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
        )
        layout.addWidget(desc)
        return card


__all__ = ["DataWindow"]
