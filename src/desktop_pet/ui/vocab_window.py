"""ui.vocab_window —— 独立非模态「生词本」窗口（JP-10/12/16）。

仅负责展示与发信号，**不直接读写存储**（写入一律经 ``app/controller`` → ``core.vocab_store``）。
等级筛选为**纯展示过滤**，在本窗口本地执行。

- 列：单词 / 假名 / 翻译 / 等级（默认按加入时间倒序 = 新在前）。
- 操作：等级下拉筛选、删除选中、清空（二次确认）、关闭。
- 空态：列表为空时居中显示 :data:`C.JP_VOCAB_EMPTY_TEXT`。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.vocab_store import VocabItem

logger = logging.getLogger(__name__)


class VocabWindow(QWidget):
    """生词本查看与管理窗口（普通顶层窗口，可最小化）。"""

    remove_requested = Signal(str)  # 携带 item id
    clear_requested = Signal()      # 二次确认通过后发出

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造生词本窗口。"""

        super().__init__(parent)
        self.setWindowTitle(C.JP_VOCAB_WINDOW_TITLE)
        self.resize(C.VOCAB_WINDOW_W, C.VOCAB_WINDOW_H)

        self._all_items: list[VocabItem] = []
        self._shown_items: list[VocabItem] = []

        self._build_ui()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def refresh(self, items: list[VocabItem]) -> None:
        """由 controller 喂入全量数据；本地按等级筛选后刷新显示。"""

        self._all_items = list(items)
        self._apply_filter()

    def level_filter(self) -> str:
        """返回当前筛选等级（``"全部"`` 或 ``"N5".."N1"``）。"""

        data = self._combo.currentData()
        return str(data) if data else C.JP_VOCAB_FILTER_ALL

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """构建界面元素与布局。"""

        root = QVBoxLayout(self)

        # 顶部：等级筛选 + 操作按钮
        top = QHBoxLayout()
        top.addWidget(QLabel(C.JP_VOCAB_LEVEL_FILTER_LABEL))
        self._combo = QComboBox(self)
        self._combo.addItem(C.JP_VOCAB_FILTER_ALL, C.JP_VOCAB_FILTER_ALL)
        for level in C.JP_LEVELS:
            self._combo.addItem(C.JP_LEVEL_LABELS.get(level, level), level)
        self._combo.currentIndexChanged.connect(lambda _idx: self._apply_filter())
        top.addWidget(self._combo)
        top.addStretch(1)
        self._btn_remove = QPushButton(C.JP_VOCAB_BTN_REMOVE, self)
        self._btn_remove.clicked.connect(self._on_remove_clicked)
        self._btn_remove.setEnabled(False)
        top.addWidget(self._btn_remove)
        self._btn_clear = QPushButton(C.JP_VOCAB_BTN_CLEAR, self)
        self._btn_clear.clicked.connect(self._on_clear_clicked)
        top.addWidget(self._btn_clear)
        root.addLayout(top)

        # 中部：表格 / 空态 二选一
        self._stack = QStackedWidget(self)
        self._table = QTableWidget(0, 4, self)
        self._table.setHorizontalHeaderLabels(
            [
                C.JP_VOCAB_COL_WORD,
                C.JP_VOCAB_COL_KANA,
                C.JP_VOCAB_COL_TRANSLATION,
                C.JP_VOCAB_COL_LEVEL,
            ]
        )
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        self._stack.addWidget(self._table)

        self._empty_label = QLabel(C.JP_VOCAB_EMPTY_TEXT, self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._stack.addWidget(self._empty_label)
        root.addWidget(self._stack, 1)

        # 底部：数量状态 + 关闭
        bottom = QHBoxLayout()
        self._status = QLabel("", self)
        bottom.addWidget(self._status)
        bottom.addStretch(1)
        self._btn_close = QPushButton(C.JP_VOCAB_BTN_CLOSE, self)
        self._btn_close.clicked.connect(self.close)
        bottom.addWidget(self._btn_close)
        root.addLayout(bottom)

        self._apply_filter()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _apply_filter(self) -> None:
        """按当前筛选等级刷新表格（纯展示过滤；新在前）。"""

        level = self.level_filter()
        if level == C.JP_VOCAB_FILTER_ALL:
            shown = list(reversed(self._all_items))
        else:
            shown = [item for item in reversed(self._all_items) if item.level == level]
        self._shown_items = shown

        self._table.setRowCount(len(shown))
        level_color = QColor(C.COLORS["vocab_level_tag"])
        for row, item in enumerate(shown):
            cells = (item.word, item.kana, item.translation, item.level)
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(str(text))
                if col == 3:
                    cell.setForeground(level_color)
                self._table.setItem(row, col, cell)

        self._status.setText(C.JP_VOCAB_STATUS_TEMPLATE.format(count=len(shown)))
        if shown:
            self._stack.setCurrentWidget(self._table)
        else:
            self._stack.setCurrentWidget(self._empty_label)

        self._btn_clear.setEnabled(bool(self._all_items))
        self._btn_remove.setEnabled(False)

    def _on_selection_changed(self) -> None:
        """选中行变化 → 更新「删除选中」可用性。"""

        self._btn_remove.setEnabled(self._table.currentRow() >= 0)

    def _on_remove_clicked(self) -> None:
        """删除选中行：只发信号，由 controller 执行删除。"""

        row = self._table.currentRow()
        if row < 0 or row >= len(self._shown_items):
            return
        self.remove_requested.emit(self._shown_items[row].id)

    def _on_clear_clicked(self) -> None:
        """清空全部：二次确认通过后发信号。"""

        if not self._all_items:
            return
        reply = QMessageBox.question(
            self,
            C.JP_VOCAB_CLEAR_CONFIRM_TITLE,
            C.JP_VOCAB_CLEAR_CONFIRM_TEXT,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.clear_requested.emit()


__all__ = ["VocabWindow"]
