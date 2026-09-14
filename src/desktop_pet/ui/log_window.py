"""ui.log_window —— 只读「学习记录」回查窗口（JP-17+）。

仅负责展示与**本地筛选**，**不直接读写存储**（数据一律经 ``app/controller`` → ``core.daily_log_store`` 喂入）。

- 顶部：日期下拉 + 状态筛选（全部 / 已掌握 / 生词 / 未处理）。
- 中部：表格（单词 / 假名 / 翻译 / 展示时间 / 状态，状态用颜色标签）。
- 底部：统计栏（当日 shown/limit · 已掌握 · 生词 · 未处理）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.daily_log_store import DailyLogEntry

logger = logging.getLogger(__name__)

#: 状态 → 显示文案
_STATUS_LABELS: dict[str, str] = {
    C.DAILY_LOG_STATUS_MASTERED: C.JP_LOG_STATUS_MASTERED,
    C.DAILY_LOG_STATUS_VOCAB: C.JP_LOG_STATUS_VOCAB,
    C.DAILY_LOG_STATUS_UNPROCESSED: C.JP_LOG_STATUS_UNPROCESSED,
}
#: 状态 → 标签颜色 key
_STATUS_COLOR_KEYS: dict[str, str] = {
    C.DAILY_LOG_STATUS_MASTERED: "log_status_mastered",
    C.DAILY_LOG_STATUS_VOCAB: "log_status_vocab",
    C.DAILY_LOG_STATUS_UNPROCESSED: "log_status_unprocessed",
}


class LogWindow(QWidget):
    """学习记录回查窗口（普通顶层窗口，纯展示）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造学习记录窗口。"""

        super().__init__(parent)
        self.setWindowTitle(C.JP_LOG_WINDOW_TITLE)
        self.resize(C.JP_LOG_WINDOW_W, C.JP_LOG_WINDOW_H)

        #: day → 该日记录缓存（controller 逐日喂入，本地切换日期即可回查）
        self._entries_by_day: dict[str, list[DailyLogEntry]] = {}
        self._shown_entries: list[DailyLogEntry] = []
        self._limit: int = C.JP_DAILY_LIMIT

        self._build_ui()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def set_dates(self, dates: list[str]) -> None:
        """填充日期下拉（controller 喂入 ``daily_log.days()``）。"""

        self._combo_date.blockSignals(True)
        self._combo_date.clear()
        for day in dates:
            self._combo_date.addItem(str(day), str(day))
        self._combo_date.blockSignals(False)

    def refresh(self, day: str, entries: list[DailyLogEntry], limit: int) -> None:
        """由 controller 喂入某天的记录并刷新显示（同时选中该天）。"""

        key = str(day)
        self._entries_by_day[key] = list(entries)
        self._limit = int(limit)
        self._ensure_date(key)
        idx = self._combo_date.findData(key)
        if idx >= 0:
            self._combo_date.setCurrentIndex(idx)
        self._apply_filter()

    def current_day(self) -> str:
        """返回当前选中日期 key（空选择返回空串）。"""

        data = self._combo_date.currentData()
        return str(data) if data else ""

    def current_status(self) -> str:
        """返回当前状态筛选：``"全部"`` / ``mastered`` / ``vocab`` / ``unprocessed``。"""

        data = self._combo_status.currentData()
        return str(data) if data else C.JP_LOG_FILTER_ALL

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """构建界面元素与布局。"""

        root = QVBoxLayout(self)

        # 顶部：日期 + 状态筛选
        top = QHBoxLayout()
        top.addWidget(QLabel(C.JP_LOG_DATE_LABEL))
        self._combo_date = QComboBox(self)
        self._combo_date.currentIndexChanged.connect(lambda _idx: self._apply_filter())
        top.addWidget(self._combo_date)
        top.addSpacing(12)
        top.addWidget(QLabel(C.JP_LOG_STATUS_LABEL))
        self._combo_status = QComboBox(self)
        self._combo_status.addItem(C.JP_LOG_FILTER_ALL, C.JP_LOG_FILTER_ALL)
        for status in C.DAILY_LOG_STATUSES:
            self._combo_status.addItem(_STATUS_LABELS[status], status)
        self._combo_status.currentIndexChanged.connect(lambda _idx: self._apply_filter())
        top.addWidget(self._combo_status)
        top.addStretch(1)
        root.addLayout(top)

        # 中部：表格
        self._table = QTableWidget(0, 5, self)
        self._table.setHorizontalHeaderLabels(
            [
                C.JP_LOG_COL_WORD,
                C.JP_LOG_COL_KANA,
                C.JP_LOG_COL_TRANSLATION,
                C.JP_LOG_COL_SHOWN_AT,
                C.JP_LOG_COL_STATUS,
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
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        root.addWidget(self._table, 1)

        # 底部：统计栏
        bottom = QHBoxLayout()
        self._status_label = QLabel("", self)
        bottom.addWidget(self._status_label)
        bottom.addStretch(1)
        root.addLayout(bottom)

        self._apply_filter()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _ensure_date(self, day: str) -> None:
        """确保日期下拉中存在 ``day``（不在 ``set_dates`` 列表里时补入）。"""

        if self._combo_date.findData(day) >= 0:
            return
        self._combo_date.blockSignals(True)
        self._combo_date.addItem(day, day)
        self._combo_date.blockSignals(False)

    def _apply_filter(self) -> None:
        """按当前日期 + 状态刷新表格与统计栏（纯展示过滤）。"""

        day = self.current_day()
        day_entries = self._entries_by_day.get(day, [])

        status = self.current_status()
        if status == C.JP_LOG_FILTER_ALL:
            shown = list(day_entries)
        else:
            shown = [entry for entry in day_entries if entry.status == status]
        self._shown_entries = shown

        self._table.setRowCount(len(shown))
        for row, entry in enumerate(shown):
            label = _STATUS_LABELS.get(entry.status, entry.status)
            cells = (entry.word, entry.kana, entry.translation, entry.shown_at, label)
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(str(text))
                if col == 4:
                    color_key = _STATUS_COLOR_KEYS.get(entry.status)
                    if color_key:
                        cell.setForeground(QColor(C.COLORS[color_key]))
                self._table.setItem(row, col, cell)

        # 统计栏以「当日全量」计（不受状态筛选影响）
        mastered = sum(
            1 for e in day_entries if e.status == C.DAILY_LOG_STATUS_MASTERED
        )
        vocab = sum(1 for e in day_entries if e.status == C.DAILY_LOG_STATUS_VOCAB)
        unprocessed = sum(
            1 for e in day_entries if e.status == C.DAILY_LOG_STATUS_UNPROCESSED
        )
        self._status_label.setText(
            C.JP_LOG_STATUS_TEMPLATE.format(
                shown=len(day_entries),
                limit=self._limit,
                mastered=mastered,
                vocab=vocab,
                unprocessed=unprocessed,
            )
        )


__all__ = ["LogWindow"]
