"""ui.mastered_window —— 独立非模态「已掌握词库」窗口（记忆曲线 JP-M）。

与 :class:`~desktop_pet.ui.vocab_window.VocabWindow` 同构（卡片列表 + 等级 Tab + 顶部操作），
仅负责展示与发信号，**不直接读写存储**（写入一律经 ``app/controller`` → ``core.mastered_store``）。
等级筛选为**纯展示过滤**，在本窗口本地执行。

- 顶部：等级文字 Tab（全部 / N5..N1）+ 立即复习 / 退回生词本 / 清空。
- 中部：卡片式词条列表——每张卡片「单词 | 假名」大字行 + 可点击喇叭，
  次行等级 chip + 中文翻译，末行**记忆状态行**（记忆阶段 / 到期描述 / 已复习次数）。
  排序：复习中的词按 ``due_at`` 升序（最早到期在最上），已毕业的排最后。
- 空态：列表为空时居中显示 :data:`C.JP_MASTERED_EMPTY_TEXT`。

到期描述（「待复习 / N 天后复习 / 已毕业」）由本窗口按 ``due_at`` 计算——
展示层职责；core 层保持零 ``datetime``（存储只存 ISO 字符串）。
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Final

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
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
from desktop_pet.core.mastered_store import MasteredItem
from desktop_pet.core.tts_client import spoken_text
from desktop_pet.ui import icon_factory, motion_ui, theme
from desktop_pet.ui.confirm_dialog import ConfirmDialog
from desktop_pet.ui.speaker_button import PronunciationController, SpeakerButton

logger = logging.getLogger(__name__)

#: ISO8601 UTC 定长格式（与 app 层 :meth:`_now_iso` 同一不变式）
_ISO_FMT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"
#: 一天的秒数（到期描述按天粒度）
_DAY_S: Final[int] = 86400


def _parse_iso(value: str) -> "datetime | None":
    """解析 ISO8601 UTC 字符串；非法返回 ``None``（展示层容错，不抛）。"""

    try:
        return datetime.strptime(str(value), _ISO_FMT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _due_description(item: MasteredItem) -> tuple[str, str]:
    """把一条记录的 SRS 状态转成（状态行文案, 语义色 key）。

    - 已毕业（``stage`` 走完阶梯）→ 「已毕业 · 长期记忆」+ ``info``；
    - 未排期（``due_at`` 空，理论瞬态）→ 「待复习」+ ``warning``；
    - 已到期 → 「待复习（已过 N 天）」+ ``warning``；
    - 未到期 → 「24 小时内复习 / N 天后复习」+ 次级灰。
    """

    parts: list[str] = []
    total = len(C.REVIEW_INTERVALS_DAYS)
    color_key = "text_secondary"

    if item.stage >= total:
        parts.append(C.JP_MASTERED_GRADUATED)
        color_key = "info"
    else:
        parts.append(C.JP_MASTERED_STAGE_TEMPLATE.format(stage=item.stage + 1, total=total))
        due_dt = _parse_iso(item.due_at)
        if due_dt is None:
            parts.append(C.JP_MASTERED_DUE_NOW)
            color_key = "warning"
        else:
            now = datetime.now(timezone.utc)
            delta_s = (due_dt - now).total_seconds()
            if delta_s <= 0:
                overdue_days = int(-delta_s) // _DAY_S
                parts.append(
                    C.JP_MASTERED_DUE_OVERDUE_TEMPLATE.format(days=overdue_days)
                    if overdue_days >= 1
                    else C.JP_MASTERED_DUE_NOW
                )
                color_key = "warning"
            elif delta_s <= _DAY_S:
                parts.append(C.JP_MASTERED_DUE_SOON)
            else:
                days = (int(delta_s) + _DAY_S - 1) // _DAY_S
                parts.append(C.JP_MASTERED_DUE_IN_TEMPLATE.format(days=days))

    if item.review_count > 0:
        parts.append(C.JP_MASTERED_REVIEWED_TEMPLATE.format(count=item.review_count))
    return " · ".join(parts), color_key


class _MasteredCard(QFrame):
    """一张已掌握卡片：单击选中、双击发详情信号、点喇叭请求发音（仅转发，无业务逻辑）。"""

    clicked = Signal(str)              # 携带 item id
    double_clicked = Signal(str)       # 携带 item id
    play_requested = Signal(str, str)  # (word, kana) —— 喇叭点击

    def __init__(self, item: MasteredItem, parent: QWidget | None = None) -> None:
        """按一条已掌握记录构建卡片 UI（状态行含记忆阶段与到期描述）。"""

        super().__init__(parent)
        self._id = str(item.id)
        self._word = str(item.word or "")
        self._kana = str(item.kana or "")
        theme.set_role(self, "card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        row = QVBoxLayout(self)
        row.setContentsMargins(
            C.SPACING["md"], C.SPACING["sm"], C.SPACING["md"], C.SPACING["sm"]
        )
        row.setSpacing(C.SPACING["xs"])

        # 行 1：单词 | 假名（大字）+ 喇叭
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
        self._speaker = SpeakerButton(self)
        self._speaker.clicked.connect(self._on_speaker_clicked)
        top.addWidget(self._speaker)
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

        # 行 3：记忆状态行（阶段 / 到期描述 / 复习次数；到期时琥珀色提醒）
        status_text, color_key = _due_description(item)
        status_label = QLabel(status_text, self)
        status_label.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS.get(color_key, C.SEMANTIC_COLORS['text_secondary'])};"
            f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
        )
        row.addWidget(status_label)

    # ------------------------------------------------------------------ #
    # 交互转发（无业务）
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """单击 → 发选中信号（窗口统一高亮并启用顶部按钮）。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._id)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """双击 → 发详情信号（controller 打开词条详情窗口）。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit(self._id)
        super().mouseDoubleClickEvent(event)

    def pronunciation_key(self) -> str:
        """本卡片的发音键（= 发音文本，与控制器广播的 ``key`` 同口径）。"""

        return spoken_text(self._word, self._kana)

    def set_speaker_state(self, state: str, message: str = "") -> None:
        """刷新喇叭三态（由窗口按发音键过滤后调用）。"""

        self._speaker.set_state(state, message)

    def _on_speaker_clicked(self) -> None:
        """点击喇叭 → 只转发请求。"""

        self.play_requested.emit(self._word, self._kana)


class MasteredWindow(QWidget):
    """已掌握词库查看与管理窗口（普通顶层窗口，可最小化）。"""

    review_requested = Signal(str)         # 立即复习选中词（携带 item id）
    back_to_vocab_requested = Signal(str)  # 退回生词本（携带 item id）
    clear_requested = Signal()             # 二次确认通过后发出
    word_double_clicked = Signal(str)      # 双击打开详情（携带 item id）

    def __init__(
        self,
        pronunciation: "PronunciationController | None" = None,
        parent: QWidget | None = None,
    ) -> None:
        """构造已掌握词库窗口。

        Args:
            pronunciation: 发音控制器（app 层单例注入）；``None`` 时喇叭可点但无效果。
            parent: 父窗口。
        """

        super().__init__(parent)
        self.setWindowTitle(C.JP_MASTERED_WINDOW_TITLE)
        self.resize(C.VOCAB_WINDOW_W, C.VOCAB_WINDOW_H)

        self._all_items: list[MasteredItem] = []
        self._shown_items: list[MasteredItem] = []
        self._selected_id: str = ""
        self._card_by_id: dict[str, _MasteredCard] = {}
        self._pronunciation: PronunciationController | None = pronunciation
        if self._pronunciation is not None:
            self._pronunciation.state_changed.connect(self._on_pronunciation_state)
        #: 「减少动效」开关（由 controller 在窗口显示前经 :meth:`set_reduce_motion` 注入）。
        self._reduce_motion: bool = False

        self._build_ui()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def refresh(self, items: list[MasteredItem]) -> None:
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
        """应用主题点缀色（controller 在窗口创建与换肤时调用）。"""

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
        """构建界面元素与布局（结构对齐生词本窗口）。"""

        theme.apply_theme(self)

        root = QVBoxLayout(self)

        # 顶部：等级 Tab + 操作按钮
        top = QHBoxLayout()
        self._tab_buttons: dict[str, QPushButton] = {}
        for value in [C.JP_VOCAB_FILTER_ALL, *C.JP_LEVELS]:
            label = (
                value
                if value == C.JP_VOCAB_FILTER_ALL
                else C.JP_LEVEL_LABELS.get(value, value)
            )
            button = QPushButton(label, self)
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setChecked(value == C.JP_VOCAB_FILTER_ALL)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            theme.set_variant(button, "tab")
            button.clicked.connect(lambda _checked=False, v=value: self._on_tab_selected(v))
            self._tab_buttons[value] = button
            top.addWidget(button)
        top.addStretch(1)
        self._btn_review = QPushButton(C.JP_MASTERED_BTN_REVIEW, self)
        theme.set_variant(self._btn_review, "primary")
        self._btn_review.clicked.connect(self._on_review_clicked)
        self._btn_review.setEnabled(False)
        top.addWidget(self._btn_review)
        self._btn_back = QPushButton(C.JP_MASTERED_BTN_BACK, self)
        theme.set_variant(self._btn_back, "secondary")
        self._btn_back.clicked.connect(self._on_back_clicked)
        self._btn_back.setEnabled(False)
        top.addWidget(self._btn_back)
        self._btn_clear = QPushButton(C.JP_MASTERED_BTN_CLEAR, self)
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

        self._empty_label = QLabel(C.JP_MASTERED_EMPTY_TEXT, self)
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setWordWrap(True)
        self._stack.addWidget(self._empty_label)
        root.addWidget(self._stack, 1)

        # 底部：数量状态 + 关闭
        bottom = QHBoxLayout()
        self._status = QLabel("", self)
        bottom.addWidget(self._status)
        bottom.addStretch(1)
        self._btn_close = QPushButton(C.JP_MASTERED_BTN_CLOSE, self)
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
        """切换等级 Tab → 重新过滤。"""

        self._apply_filter()

    def _sorted_items(self, level: str) -> list[MasteredItem]:
        """展示排序：复习中按 ``due_at`` 升序（最早到期在最上）→ 已毕业垫底。

        ``due_at`` 为定长 UTC ISO 字符串，字典序即时间序；空 ``due_at``（未排期
        瞬态）排在最前提醒处理。已毕业按掌握时间倒序（新毕业在前）。
        """

        total = len(C.REVIEW_INTERVALS_DAYS)
        items = [it for it in self._all_items if level == C.JP_VOCAB_FILTER_ALL or it.level == level]
        reviewing = [it for it in items if it.stage < total]
        graduated = [it for it in items if it.stage >= total]
        reviewing.sort(key=lambda it: (it.due_at != "", it.due_at))
        graduated.sort(key=lambda it: it.mastered_at, reverse=True)
        return reviewing + graduated

    def _apply_filter(self) -> None:
        """按当前筛选等级刷新卡片列表（纯展示过滤）。"""

        shown = self._sorted_items(self.level_filter())
        self._shown_items = shown
        self._selected_id = ""
        self._btn_review.setEnabled(False)
        self._btn_back.setEnabled(False)

        # 重建卡片列表（已掌握量级 = 用户掌握量，整表重建足够快）
        self._card_by_id.clear()
        while self._cards_layout.count() > 1:  # 末尾 stretch 保留
            item = self._cards_layout.takeAt(0)
            widget = item.widget() if item is not None else None
            if widget is not None:
                widget.deleteLater()
        for item in shown:
            card = _MasteredCard(item, self._cards_host)
            card.clicked.connect(self._on_card_clicked)
            card.double_clicked.connect(self.word_double_clicked)
            card.play_requested.connect(self._on_card_play_requested)
            self._cards_layout.insertWidget(self._cards_layout.count() - 1, card)
            self._card_by_id[item.id] = card

        due_count = sum(
            1
            for it in self._all_items
            if it.stage < len(C.REVIEW_INTERVALS_DAYS)
            and it.due_at
            and it.due_at <= datetime.now(timezone.utc).strftime(_ISO_FMT)
        )
        self._status.setText(
            C.JP_MASTERED_STATUS_TEMPLATE.format(count=len(self._all_items), due=due_count)
        )
        if shown:
            self._stack.setCurrentWidget(self._scroll)
        else:
            self._stack.setCurrentWidget(self._empty_label)

        self._btn_clear.setEnabled(bool(self._all_items))

    def _on_card_clicked(self, item_id: str) -> None:
        """单击卡片 → 选中高亮 + 启用「立即复习 / 退回生词本」。"""

        self._selected_id = str(item_id)
        for wid, card in self._card_by_id.items():
            theme.set_card_selected(card, wid == self._selected_id)
        self._btn_review.setEnabled(True)
        self._btn_back.setEnabled(True)

    def _on_review_clicked(self) -> None:
        """立即复习选中词：只发信号，由 controller 弹复习泡泡。"""

        if self._selected_id:
            self.review_requested.emit(self._selected_id)

    def _on_back_clicked(self) -> None:
        """退回生词本选中词：只发信号，由 controller 执行（SRS 状态一并清除）。"""

        if self._selected_id:
            self.back_to_vocab_requested.emit(self._selected_id)

    # ------------------------------------------------------------------ #
    # 发音（卡片转发 → 控制器；状态广播 → 按发音键过滤回灌卡片）
    # ------------------------------------------------------------------ #
    def _on_card_play_requested(self, word: str, kana: str) -> None:
        """卡片喇叭点击 → 交发音控制器。"""

        if self._pronunciation is None:
            return
        self._pronunciation.play(str(word), str(kana))

    def _on_pronunciation_state(self, key: str, state: str, message: str) -> None:
        """发音状态广播（主线程）→ 刷新发音键匹配的卡片喇叭三态。"""

        for card in self._card_by_id.values():
            if card.pronunciation_key() == str(key):
                card.set_speaker_state(state, message)

    def _on_clear_clicked(self) -> None:
        """清空全部：主题化二次确认通过后发信号（默认不删除）。"""

        if not self._all_items:
            return
        confirmed = ConfirmDialog.ask(
            self,
            C.JP_MASTERED_CLEAR_CONFIRM_TITLE,
            C.JP_MASTERED_CLEAR_CONFIRM_TEXT,
            C.JP_MASTERED_BTN_CLEAR,
        )
        if confirmed:
            self.clear_requested.emit()


__all__ = ["MasteredWindow"]
