"""ui.bank_window —— 「词库管理」窗口（多词库：导入 / 启停 / 删除，拖拽导入）。

仅负责展示与发信号，**不读写存储**：词库数据由 controller 聚合
（:class:`BankInfo` 列表）经 :meth:`BankWindow.refresh` 喂入；导入 / 启停 /
删除的文件操作与合并重建全部在 controller。

交互：词库卡列表（内置库固定首行不可操作）+ 拖拽 .json 入窗即导入 +
「导入词库…」按钮（文件对话框）；删除在窗口内二次确认后发信号。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.bank_registry import BankInfo
from desktop_pet.ui import icon_factory, motion_ui, theme
from desktop_pet.ui.confirm_dialog import ConfirmDialog

logger = logging.getLogger(__name__)


class _BankCard(QFrame):
    """一张词库卡：名称 + 词条计数 + 等级分布 +（非内置）启用勾选与删除。"""

    toggled = Signal(str, bool)   # (bank_id, enabled)
    delete_clicked = Signal(str)  # bank_id

    def __init__(self, info: BankInfo, parent: QWidget | None = None) -> None:
        """按展示信息构建卡片（内置库无勾选 / 删除）。"""

        super().__init__(parent)
        self._id = str(info.id)
        self._name = str(info.name)
        theme.set_role(self, "card")
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        column = QVBoxLayout(self)
        column.setContentsMargins(C.SPACING["md"], C.SPACING["sm"], C.SPACING["md"], C.SPACING["sm"])
        column.setSpacing(C.SPACING["xs"])

        # 行 1：名称 + 词条数
        top = QHBoxLayout()
        top.setSpacing(C.SPACING["sm"])
        name_label = QLabel(self._name, self)
        name_label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['body']}px; font-weight: bold;"
            f" color: {C.SEMANTIC_COLORS['text_primary']}; background: transparent;"
        )
        top.addWidget(name_label)
        top.addStretch(1)
        count_label = QLabel(
            C.BANK_WORDS_TEMPLATE.format(count=info.word_count), self
        )
        count_label.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_secondary']};"
            f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
        )
        top.addWidget(count_label)
        column.addLayout(top)

        # 行 2：等级分布（有词条才显示）
        levels_text = " · ".join(
            f"{level} {count}" for level, count in sorted(info.level_counts.items())
        )
        if levels_text:
            levels_label = QLabel(levels_text, self)
            levels_label.setStyleSheet(
                f"color: {C.SEMANTIC_COLORS['text_faint']};"
                f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
            )
            column.addWidget(levels_label)

        # 行 3：内置库提示 / 启用勾选 + 删除
        if info.builtin:
            tip_label = QLabel(C.BANK_BUILTIN_TIP, self)
            tip_label.setStyleSheet(
                f"color: {C.SEMANTIC_COLORS['text_faint']};"
                f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
            )
            column.addWidget(tip_label)
        else:
            bottom = QHBoxLayout()
            bottom.setSpacing(C.SPACING["sm"])
            checkbox = QCheckBox("启用", self)
            checkbox.setChecked(bool(info.enabled))
            checkbox.setToolTip(C.BANK_ENABLE_TIP)
            checkbox.toggled.connect(
                lambda checked, bank_id=self._id: self.toggled.emit(bank_id, checked)
            )
            bottom.addWidget(checkbox)
            bottom.addStretch(1)
            delete_button = QPushButton("删除", self)
            theme.set_variant(delete_button, "ghost")
            delete_button.clicked.connect(
                lambda _checked=False, bank_id=self._id: self._confirm_delete()
            )
            bottom.addWidget(delete_button)
            column.addLayout(bottom)

    def _confirm_delete(self) -> None:
        """删除二次确认（确认后才发信号；文件删除与合并重建在 controller）。"""

        confirmed = ConfirmDialog.ask(
            self,
            C.BANK_DELETE_CONFIRM_TITLE,
            C.BANK_DELETE_CONFIRM_TEXT.format(name=self._name),
            C.BANK_DELETE_CONFIRM_BUTTON,
        )
        if confirmed:
            self.delete_clicked.emit(self._id)


class BankWindow(QWidget):
    """词库管理窗口（普通顶层窗口，纯信号源）。"""

    toggle_requested = Signal(str, bool)       # (bank_id, enabled)
    delete_requested = Signal(str)             # bank_id（窗口内已二次确认）
    import_files_requested = Signal(list)      # [str 路径, ...]（对话框或拖拽）

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造词库管理窗口。"""

        super().__init__(parent)
        self.setWindowTitle(C.BANK_WINDOW_TITLE)
        self.resize(C.BANK_WINDOW_W, C.BANK_WINDOW_H)
        self._reduce_motion: bool = False
        self.setAcceptDrops(True)

        self._build_ui()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def refresh(self, infos: list[BankInfo], total: int) -> None:
        """由 controller 喂入词库信息并重建卡列表（每次打开 / 变更后调用）。"""

        while self._cards_layout.count() > 1:  # 末尾 stretch 保留
            item = self._cards_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for info in infos:
            card = _BankCard(info, self._cards_host)
            card.toggled.connect(self.toggle_requested)
            card.delete_clicked.connect(self.delete_requested)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
        enabled_count = sum(1 for info in infos if info.enabled and not info.builtin)
        imported_count = sum(1 for info in infos if not info.builtin)
        self._status_label.setText(
            C.BANK_STATUS_TEMPLATE.format(
                total=total, enabled=enabled_count, banks=imported_count
            )
        )
        self._empty_label.setVisible(not any(not info.builtin for info in infos))

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
    # 拖拽导入
    # ------------------------------------------------------------------ #
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        """拖入：仅当含 .json 文件 URL 时接受。"""

        if any(u.toLocalFile().lower().endswith(".json") for u in event.mimeData().urls() if u.isLocalFile()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        """放下：收集 .json 本地路径 → 发导入信号（校验在 controller）。"""

        paths = [
            u.toLocalFile()
            for u in event.mimeData().urls()
            if u.isLocalFile() and u.toLocalFile().lower().endswith(".json")
        ]
        if paths:
            event.acceptProposedAction()
            self.import_files_requested.emit(paths)

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """构建界面元素与布局。"""

        theme.apply_theme(self)
        root = QVBoxLayout(self)
        root.setSpacing(C.SPACING["sm"])

        # 中部：词库卡滚动区 / 空态
        self._stack_host = QWidget(self)
        stack_layout = QVBoxLayout(self._stack_host)
        stack_layout.setContentsMargins(0, 0, 0, 0)

        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_host = QWidget(self._scroll)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(C.SPACING["xs"], 0, C.SPACING["xs"], 0)
        self._cards_layout.setSpacing(C.SPACING["sm"])
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._cards_host)
        stack_layout.addWidget(self._scroll)

        self._empty_label = QLabel(C.BANK_EMPTY_TEXT, self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._empty_label.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_faint']};"
            f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
        )
        stack_layout.addWidget(self._empty_label)
        root.addWidget(self._stack_host, 1)

        # 底部：导入按钮 + 状态栏 + 关闭
        bottom = QHBoxLayout()
        self._btn_import = QPushButton(C.BANK_BTN_IMPORT, self)
        self._btn_import.clicked.connect(self._on_import_clicked)
        bottom.addWidget(self._btn_import)
        bottom.addStretch(1)
        self._status_label = QLabel("", self)
        bottom.addWidget(self._status_label)
        self._btn_close = QPushButton(C.BANK_BTN_CLOSE, self)
        theme.set_variant(self._btn_close, "ghost")
        self._btn_close.setIcon(
            icon_factory.make_icon("close", color=C.SEMANTIC_COLORS["text_primary"])
        )
        self._btn_close.setIconSize(QSize(C.SPACING["lg"], C.SPACING["lg"]))
        self._btn_close.clicked.connect(self.close)
        bottom.addWidget(self._btn_close)
        root.addLayout(bottom)

    def _on_import_clicked(self) -> None:
        """「导入词库…」：文件对话框（可多选）→ 发导入信号。"""

        selected, _filter = QFileDialog.getOpenFileNames(
            None,
            C.JP_IMPORT_DIALOG_TITLE,
            "",
            C.JP_IMPORT_DIALOG_FILTER,
        )
        if selected:
            self.import_files_requested.emit(list(selected))


__all__ = ["BankWindow"]
