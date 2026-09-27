"""ui.vocab_window —— 独立非模态「生词本」窗口（JP-10/12/16，卡片化改版）。

仅负责展示与发信号，**不直接读写存储**（写入一律经 ``app/controller`` → ``core.vocab_store``）。
等级筛选为**纯展示过滤**，在本窗口本地执行。

- 顶部：等级文字 Tab（全部 / N5..N1，参考移动端词典应用的下划线选中态）+ 删除/清空。
- 中部：卡片式词条列表（无表格线）——每张卡片「单词 | 假名」大字行 + 喇叭占位
  （发音功能未启用，置灰），次行等级 chip + 中文翻译 + 释义摘要；单击选中、双击详情。
- 空态：列表为空时居中显示 :data:`C.JP_VOCAB_EMPTY_TEXT`。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.vocab_store import VocabItem
from desktop_pet.ui import icon_factory, motion_ui, theme

logger = logging.getLogger(__name__)

#: 释义摘要的最大字符数（超出截断加省略号；卡片保持两行紧凑排版）。
_MEANING_PREVIEW_MAX_CHARS: Final = 40


class _WordCard(QFrame):
    """一张生词卡片：单击选中、双击发出详情信号（仅转发 id，无业务逻辑）。"""

    clicked = Signal(str)         # 携带 item id
    double_clicked = Signal(str)  # 携带 item id

    def __init__(self, item: VocabItem, item_id: str, parent: QWidget | None = None) -> None:
        """按一条生词记录构建卡片 UI（``item_id`` 作为点击信号的载荷）。"""

        super().__init__(parent)
        self._id = str(item_id)
        theme.set_role(self, "card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QVBoxLayout(self)
        row.setContentsMargins(
            C.SPACING["md"], C.SPACING["sm"], C.SPACING["md"], C.SPACING["sm"]
        )
        row.setSpacing(C.SPACING["xs"])

        # 行 1：单词 | 假名（大字）+ 喇叭占位（置灰，发音功能预留）
        top = QHBoxLayout()
        top.setSpacing(C.SPACING["sm"])
        self._word_label = QLabel(item.word, self)
        self._word_label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['title']}px; font-weight: bold;"
            f" color: {C.SEMANTIC_COLORS['text_primary']}; background: transparent;"
        )
        top.addWidget(self._word_label)
        self._kana_label = QLabel(f"｜{item.kana}", self)
        self._kana_label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['body']}px;"
            f" color: {C.SEMANTIC_COLORS['text_secondary']}; background: transparent;"
        )
        top.addWidget(self._kana_label)
        top.addStretch(1)
        speaker = QLabel(self)
        speaker.setPixmap(
            icon_factory.make_icon("speaker", color=C.SEMANTIC_COLORS["text_faint"]).pixmap(
                QSize(C.SPACING["xl"], C.SPACING["xl"])
            )
        )
        speaker.setToolTip(C.JP_SPEAKER_TIP)
        speaker.setStyleSheet("background: transparent;")
        top.addWidget(speaker)
        row.addLayout(top)

        # 行 2：等级 chip + 中文翻译
        mid = QHBoxLayout()
        mid.setSpacing(C.SPACING["sm"])
        level_chip = QLabel(item.level, self)
        theme.set_role(level_chip, "chip")
        mid.addWidget(level_chip)
        translation_label = QLabel(item.translation, self)
        translation_label.setWordWrap(True)
        translation_label.setStyleSheet("background: transparent;")
        mid.addWidget(translation_label, 1)
        row.addLayout(mid)

        # 行 3：释义摘要（次级小字，单行截断）
        if item.meaning:
            meaning_label = QLabel(self._preview(item.meaning), self)
            meaning_label.setStyleSheet(
                f"color: {C.SEMANTIC_COLORS['text_secondary']};"
                f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
            )
            row.addWidget(meaning_label)

    @staticmethod
    def _preview(meaning: str) -> str:
        """释义过长时截断加省略号（卡片内保持紧凑，完整释义看详情窗口）。"""

        text = " ".join(str(meaning).split())
        if len(text) <= _MEANING_PREVIEW_MAX_CHARS:
            return text
        return text[:_MEANING_PREVIEW_MAX_CHARS].rstrip() + "…"

    def mousePressEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """单击 → 发选中信号（卡片列表无选中伪类，用属性态高亮）。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """双击 → 发详情信号（controller 打开词条详情窗口）。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._id)
        super().mouseDoubleClickEvent(event)


class VocabWindow(QWidget):
    """生词本查看与管理窗口（普通顶层窗口，可最小化）。"""

    remove_requested = Signal(str)  # 携带 item id
    clear_requested = Signal()      # 二次确认通过后发出
    word_double_clicked = Signal(str)  # 携带 item.id（双击打开详情，P1）

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造生词本窗口。"""

        super().__init__(parent)
        self.setWindowTitle(C.JP_VOCAB_WINDOW_TITLE)
        self.resize(C.VOCAB_WINDOW_W, C.VOCAB_WINDOW_H)

        self._all_items: list[VocabItem] = []
        self._shown_items: list[VocabItem] = []
        self._selected_id: str = ""
        self._card_by_id: dict[str, _WordCard] = {}
        #: 「减少动效」开关（由 controller 在窗口显示前经 :meth:`set_reduce_motion` 注入）。
        self._reduce_motion: bool = False

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

        for value, button in self._tab_buttons.items():
            if button.isChecked():
                return value
        return C.JP_VOCAB_FILTER_ALL

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

        # 顶部：等级文字 Tab（单选）+ 操作按钮
        top = QHBoxLayout()
        self._tab_buttons: dict[str, QPushButton] = {}
        tab_values = [C.JP_VOCAB_FILTER_ALL, *C.JP_LEVELS]
        for value in tab_values:
            label = (
                value
                if value == C.JP_VOCAB_FILTER_ALL
                else C.JP_LEVEL_LABELS.get(value, value)
            )
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            # Tab 为纯点击目标：禁用焦点，避免初始焦点画出不属于选中的下划线。
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setChecked(value == C.JP_VOCAB_FILTER_ALL)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            theme.set_variant(button, "tab")
            button.clicked.connect(
                lambda _checked=False, v=value: self._on_tab_selected(v)
            )
            self._tab_buttons[value] = button
            top.addWidget(button)
        top.addStretch(1)
        self._btn_remove = QPushButton(C.JP_VOCAB_BTN_REMOVE, self)
        theme.set_variant(self._btn_remove, "secondary")
        self._btn_remove.setIcon(
            icon_factory.make_icon("remove", color=C.SEMANTIC_COLORS["text_primary"])
        )
        self._btn_remove.setIconSize(QSize(C.SPACING["lg"], C.SPACING["lg"]))
        self._btn_remove.clicked.connect(self._on_remove_clicked)
        self._btn_remove.setEnabled(False)
        top.addWidget(self._btn_remove)
        self._btn_clear = QPushButton(C.JP_VOCAB_BTN_CLEAR, self)
        theme.set_variant(self._btn_clear, "destructive")
        self._btn_clear.setIcon(
            icon_factory.make_icon("trash", color=C.SEMANTIC_COLORS["surface"])
        )
        self._btn_clear.setIconSize(QSize(C.SPACING["lg"], C.SPACING["lg"]))
        self._btn_clear.clicked.connect(self._on_clear_clicked)
        top.addWidget(self._btn_clear)
        root.addLayout(top)

        # 中部：卡片滚动区 / 空态 二选一
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
    def _on_tab_selected(self, value: str) -> None:
        """切换等级 Tab → 重新过滤（按钮互斥已由 autoExclusive 保证）。"""

        self._apply_filter()

    def _apply_filter(self) -> None:
        """按当前筛选等级刷新卡片列表（纯展示过滤；新在前）。"""

        level = self.level_filter()
        if level == C.JP_VOCAB_FILTER_ALL:
            shown = list(reversed(self._all_items))
        else:
            shown = [item for item in reversed(self._all_items) if item.level == level]
        self._shown_items = shown
        self._selected_id = ""
        self._btn_remove.setEnabled(False)

        # 重建卡片列表（生词本数据量 = 用户收录量，量级小，整表重建足够快）
        self._card_by_id.clear()
        while self._cards_layout.count() > 1:  # 末尾 stretch 保留
            item = self._cards_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for item in shown:
            card = _WordCard(item, item.id, self._cards_host)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self.word_double_clicked)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._card_by_id[item.id] = card

        self._status.setText(C.JP_VOCAB_STATUS_TEMPLATE.format(count=len(shown)))
        if shown:
            self._stack.setCurrentWidget(self._scroll)
        else:
            self._stack.setCurrentWidget(self._empty_label)

        self._btn_clear.setEnabled(bool(self._all_items))

    def _on_card_clicked(self, item_id: str) -> None:
        """单击卡片 → 选中高亮 + 启用「删除选中」。"""

        self._selected_id = str(item_id)
        for wid, card in self._card_by_id.items():
            theme.set_card_selected(card, wid == self._selected_id)
        self._btn_remove.setEnabled(True)

    def _on_remove_clicked(self) -> None:
        """删除选中卡片：只发信号，由 controller 执行删除。"""

        if self._selected_id:
            self.remove_requested.emit(self._selected_id)

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
