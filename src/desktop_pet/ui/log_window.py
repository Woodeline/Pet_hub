"""ui.log_window —— 只读「学习记录」回查窗口（JP-17+，卡片化改版）。

仅负责展示与**本地筛选**，**不直接读写存储**（数据一律经 ``app/controller`` → ``core.daily_log_store`` 喂入）。

- 顶部：日期下拉 + 状态文字 Tab（全部 / 已掌握 / 生词 / 未处理）。
- 中部：卡片式列表（无表格线）——每张卡片「单词 | 假名」+ 状态彩色标签 +
  展示时间，次行中文翻译；双击卡片打开词条详情。
- 底部：统计栏（当日 shown/limit · 已掌握 · 生词 · 未处理）。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.daily_log_store import DailyLogEntry
from desktop_pet.ui import icon_factory, motion_ui, theme

logger = logging.getLogger(__name__)

#: 状态 → 显示文案
_STATUS_LABELS: dict[str, str] = {
    C.DAILY_LOG_STATUS_MASTERED: C.JP_LOG_STATUS_MASTERED,
    C.DAILY_LOG_STATUS_VOCAB: C.JP_LOG_STATUS_VOCAB,
    C.DAILY_LOG_STATUS_UNPROCESSED: C.JP_LOG_STATUS_UNPROCESSED,
    C.DAILY_LOG_STATUS_REVIEW_OK: C.JP_LOG_STATUS_REVIEW_OK,
    C.DAILY_LOG_STATUS_REVIEW_LAPSED: C.JP_LOG_STATUS_REVIEW_LAPSED,
}
#: 状态 → 语义色 key（指向 ``SEMANTIC_COLORS``）。
# P1 三态映射依据（计划 §3）：已掌握=信息色 ``info``；生词从「蓝」改为琥珀 ``warning``
# 以与信息色解耦；未处理=次级灰 ``text_secondary``——原用 ``muted`` 与 ``text_faint`` 同值
# ``#98A2AD``，在 ``surface`` ``#FFFFFF`` 上对比度仅 2.59（偏低、不易辨认），
# 提升为 ``text_secondary`` ``#5A626C``（对比度 6.18）以改善可读性。
# 复习两态（记忆曲线）：记得=正向绿 ``success``；忘了=警示红 ``destructive``。
_STATUS_COLOR_KEYS: dict[str, str] = {
    C.DAILY_LOG_STATUS_MASTERED: "info",
    C.DAILY_LOG_STATUS_VOCAB: "warning",
    C.DAILY_LOG_STATUS_UNPROCESSED: "text_secondary",
    C.DAILY_LOG_STATUS_REVIEW_OK: "success",
    C.DAILY_LOG_STATUS_REVIEW_LAPSED: "destructive",
}


class _LogCard(QFrame):
    """一条学习记录卡片：双击发出详情信号（仅转发 id，无业务逻辑）。"""

    double_clicked = Signal(str)  # 携带 entry id

    def __init__(self, entry: DailyLogEntry, parent: QWidget | None = None) -> None:
        """按一条记录构建卡片 UI（状态标签用对应语义色）。"""

        super().__init__(parent)
        theme.set_role(self, "card")
        self._id = str(entry.id)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QVBoxLayout(self)
        row.setContentsMargins(
            C.SPACING["md"], C.SPACING["sm"], C.SPACING["md"], C.SPACING["sm"]
        )
        row.setSpacing(C.SPACING["xs"])

        # 行 1：单词 | 假名 + 状态标签 + 展示时间
        top = QHBoxLayout()
        top.setSpacing(C.SPACING["sm"])
        word_label = QLabel(entry.word, self)
        word_label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['title']}px; font-weight: bold;"
            f" color: {C.SEMANTIC_COLORS['text_primary']}; background: transparent;"
        )
        top.addWidget(word_label)
        kana_label = QLabel(f"｜{entry.kana}", self)
        kana_label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['body']}px;"
            f" color: {C.SEMANTIC_COLORS['text_secondary']}; background: transparent;"
        )
        top.addWidget(kana_label)
        top.addStretch(1)
        # 三态齐平：三种状态都渲染状态标签（此前把「未处理」排除在外，导致
        # 未处理卡片无状态提示、且未处理文字对比度提升改动无使用路径）。
        color_key = _STATUS_COLOR_KEYS.get(entry.status)
        status_text = _STATUS_LABELS.get(entry.status, entry.status)
        if color_key:
            status_label = QLabel(status_text, self)
            status_label.setStyleSheet(
                f"color: {C.SEMANTIC_COLORS[color_key]};"
                f" font-size: {C.FONT_SIZE['caption']}px; font-weight: bold;"
                " background: transparent;"
            )
            top.addWidget(status_label)
        shown_at = QLabel(str(entry.shown_at), self)
        shown_at.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_faint']};"
            f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
        )
        top.addWidget(shown_at)
        row.addLayout(top)

        # 行 2：中文翻译
        translation_label = QLabel(entry.translation, self)
        translation_label.setWordWrap(True)
        translation_label.setStyleSheet("background: transparent;")
        row.addWidget(translation_label)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """双击 → 发详情信号（controller 打开词条详情窗口）。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._id)
        super().mouseDoubleClickEvent(event)


class LogWindow(QWidget):
    """学习记录回查窗口（普通顶层窗口，纯展示）。"""

    word_double_clicked = Signal(str)  # 携带 entry.id

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造学习记录窗口。"""

        super().__init__(parent)
        self.setWindowTitle(C.JP_LOG_WINDOW_TITLE)
        self.resize(C.JP_LOG_WINDOW_W, C.JP_LOG_WINDOW_H)

        #: day → 该日记录缓存（controller 逐日喂入，本地切换日期即可回查）
        self._entries_by_day: dict[str, list[DailyLogEntry]] = {}
        self._shown_entries: list[DailyLogEntry] = []
        self._card_by_id: dict[str, _LogCard] = {}
        self._limit: int = C.JP_DAILY_LIMIT
        #: 「减少动效」开关（由 controller 在窗口显示前经 :meth:`set_reduce_motion` 注入）。
        self._reduce_motion: bool = False

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

        for value, button in self._tab_buttons.items():
            if button.isChecked():
                return value
        return C.JP_LOG_FILTER_ALL

    def set_reduce_motion(self, flag: bool) -> None:
        """注入「减少动效」开关（由 controller 在窗口显示前调用）。"""

        self._reduce_motion = bool(flag)

    def set_accent(self, accent: str | None) -> None:
        """应用主题点缀色（controller 在窗口创建与换肤时调用；``None`` 回落中性）。"""

        theme.apply_theme(self, accent)

    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """关闭：开启动效且窗口可见时先淡出再隐藏，否则沿用默认关闭。"""

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

        # 统一接入语义 token（QSS 由 theme 生成）。
        theme.apply_theme(self)

        root = QVBoxLayout(self)

        # 顶部：日期 + 状态 Tab
        top = QHBoxLayout()
        top.addWidget(QLabel(C.JP_LOG_DATE_LABEL))
        self._combo_date = QComboBox(self)
        self._combo_date.currentIndexChanged.connect(lambda _idx: self._apply_filter())
        top.addWidget(self._combo_date)
        top.addSpacing(C.SPACING["xl"])
        self._tab_buttons: dict[str, QPushButton] = {}
        tab_defs = [(C.JP_LOG_FILTER_ALL, C.JP_LOG_FILTER_ALL)] + [
            (status, _STATUS_LABELS[status]) for status in C.DAILY_LOG_STATUSES
        ]
        for value, label in tab_defs:
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            # Tab 为纯点击目标：禁用焦点，避免初始焦点画出不属于选中的下划线。
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setChecked(value == C.JP_LOG_FILTER_ALL)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            theme.set_variant(button, "tab")
            button.clicked.connect(lambda _checked=False: self._apply_filter())
            self._tab_buttons[value] = button
            top.addWidget(button)
        top.addStretch(1)
        root.addLayout(top)

        # 中部：卡片滚动区 / 空态
        self._stack = QStackedWidget(self)
        self._scroll = QScrollArea(self)
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._cards_host = QWidget(self._scroll)
        self._cards_layout = QVBoxLayout(self._cards_host)
        self._cards_layout.setContentsMargins(C.SPACING["xs"], 0, C.SPACING["xs"], 0)
        self._cards_layout.setSpacing(C.SPACING["sm"])
        self._cards_layout.addStretch(1)
        self._scroll.setWidget(self._cards_host)
        self._stack.addWidget(self._scroll)

        self._empty_label = QLabel(C.JP_LOG_EMPTY_TEXT, self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._stack.addWidget(self._empty_label)
        root.addWidget(self._stack, 1)

        # 底部：统计栏 + 关闭（与生词本底栏结构对齐）
        bottom = QHBoxLayout()
        self._status_label = QLabel("", self)
        bottom.addWidget(self._status_label)
        bottom.addStretch(1)
        self._btn_close = QPushButton(C.JP_LOG_BTN_CLOSE, self)
        theme.set_variant(self._btn_close, "ghost")
        self._btn_close.setIcon(
            icon_factory.make_icon("close", color=C.SEMANTIC_COLORS["text_primary"])
        )
        self._btn_close.setIconSize(QSize(C.SPACING["lg"], C.SPACING["lg"]))
        self._btn_close.clicked.connect(self.close)
        bottom.addWidget(self._btn_close)
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
        """按当前日期 + 状态刷新卡片列表与统计栏（纯展示过滤）。"""

        day = self.current_day()
        day_entries = self._entries_by_day.get(day, [])

        status = self.current_status()
        if status == C.JP_LOG_FILTER_ALL:
            shown = list(day_entries)
        else:
            shown = [entry for entry in day_entries if entry.status == status]
        self._shown_entries = shown

        # 重建卡片列表（每日上限最高 30 + 手动展示，量级小，整表重建足够快）
        self._card_by_id.clear()
        while self._cards_layout.count() > 1:  # 末尾 stretch 保留
            item = self._cards_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for entry in shown:
            card = _LogCard(entry, self._cards_host)
            card.double_clicked.connect(self.word_double_clicked)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._card_by_id[str(entry.id)] = card

        if shown:
            self._stack.setCurrentWidget(self._scroll)
        else:
            self._stack.setCurrentWidget(self._empty_label)

        # 统计栏以「当日全量」计（不受状态筛选影响）
        mastered = sum(
            1 for e in day_entries if e.status == C.DAILY_LOG_STATUS_MASTERED
        )
        vocab = sum(1 for e in day_entries if e.status == C.DAILY_LOG_STATUS_VOCAB)
        unprocessed = sum(
            1 for e in day_entries if e.status == C.DAILY_LOG_STATUS_UNPROCESSED
        )
        review_ok = sum(
            1 for e in day_entries if e.status == C.DAILY_LOG_STATUS_REVIEW_OK
        )
        review_lapsed = sum(
            1 for e in day_entries if e.status == C.DAILY_LOG_STATUS_REVIEW_LAPSED
        )
        self._status_label.setText(
            C.JP_LOG_STATUS_TEMPLATE.format(
                shown=len(day_entries),
                limit=self._limit,
                mastered=mastered,
                vocab=vocab,
                unprocessed=unprocessed,
                review_ok=review_ok,
                review_lapsed=review_lapsed,
            )
        )


__all__ = ["LogWindow"]
