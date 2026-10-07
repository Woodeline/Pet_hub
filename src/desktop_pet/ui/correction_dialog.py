"""ui.correction_dialog —— 词条纠错对话框（划旧写新：字段 chips + 旧值删除线对照）。

职责边界（对齐 ui 层其它业务窗口）：

- 只做「选择与编辑」的 UI：确定时经 :attr:`applied` 信号交回
  ``(item_id, word, field, new_value, note)``，由 controller 落盘覆盖层、
  同步快照、重建词库并给托盘反馈；
- 「系统确认」= 提交时的行内校验（非空 / 与当前值不同 / 读音须纯假名，
  复用 :func:`~desktop_pet.core.tts_client.is_pure_kana`），校验不过对话框不关；
- 撤销：该词已有纠错记录逐条列出，点击「撤销」发 :attr:`undo_requested`
  ``(item_id, field)``，controller 删记录后重建词库并按 ``old_value`` 还原快照；
- 读音字段支持点击喇叭**试听新读音**（``PronunciationController.play(word, 新假名)``，
  发音键随新假名自动变化，无需清发音缓存）。

视觉（2026-10-07 重设计）：单张连续白面，三段内容以发丝线分隔，词条头沿用
详情窗口的词典卡片语言（大号单词 + 假名 + 等级 chip）；唯一强调是「划旧写新」
——被纠正的旧值以删除线浅墨色紧贴新值输入框；字段选择用四个可点选 chips
（封闭四选一，替换下拉框）。色值全部取自 design token，错误提示是全对话框
唯一的红色。

业务规则（词库纠错覆盖层，详见 ``core.corrections_store``）：词库文件永不改写，
纠错只记录「某词条某字段 → 新值」，每次合并词库后统一套用；学习进度
（已掌握 SRS 阶梯 / 生词本加入时间）不受纠错影响。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.corrections_store import CorrectionItem
from desktop_pet.core.tts_client import is_pure_kana
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.ui import theme
from desktop_pet.ui.speaker_button import PronunciationController, SpeakerButton

logger = logging.getLogger(__name__)

#: 删除线旧值的最大宽度（px）：超过即中段省略（完整值进 tooltip）
_OLD_VALUE_MAX_W: int = 160

__all__ = ["CorrectionDialog"]


class CorrectionDialog(QDialog):
    """词条纠错对话框（模态，controller 单例持有）。

    用法（controller）::

        dlg = CorrectionDialog(pronunciation=self._pronunciation)
        dlg.applied.connect(self._on_correction_applied)
        dlg.undo_requested.connect(self._on_correction_undo)
        dlg.finished.connect(self._on_correction_dialog_closed)
        dlg.open_for(entry, self._corrections.items_for(entry.id))
        dlg.show()
    """

    #: 确认提交：(词条 id, 表记, 字段名, 新值, 备注) —— 校验通过后发出
    applied = Signal(str, str, str, str, str)
    #: 点击某条已有纠错的「撤销」：(词条 id, 字段名)
    undo_requested = Signal(str, str)

    def __init__(
        self,
        pronunciation: PronunciationController | None = None,
        parent=None,
    ) -> None:
        """构造对话框。

        Args:
            pronunciation: 发音控制器（app 层单例注入）；``None`` 时隐藏试听喇叭。
            parent: Qt 父对象。
        """

        super().__init__(parent)
        self.setWindowTitle(C.APP_DISPLAY_NAME + " · " + C.CORRECTION_DIALOG_TITLE)
        self.setModal(True)
        theme.apply_theme(self)

        self._entry: VocabEntry | None = None
        self._pronunciation = pronunciation

        # —— ① 词条头（词典卡片语言，与详情窗口同族）：大号单词 + 假名 + 等级 chip ——
        header = QHBoxLayout()
        self._word_label = QLabel()
        self._word_label.setStyleSheet(
            "QLabel { font-size: "
            f"{C.FONT_SIZE['display']}px; font-weight: bold;"
            f" color: {C.SEMANTIC_COLORS['text_primary']};"
            " }"
        )
        header.addWidget(self._word_label)
        self._kana_label = QLabel()
        self._kana_label.setStyleSheet(
            f"QLabel {{ color: {C.SEMANTIC_COLORS['text_secondary']}; }}"
        )
        header.addWidget(self._kana_label)
        header.addStretch(1)
        self._level_chip = QLabel()
        theme.set_role(self._level_chip, "chip")
        header.addWidget(self._level_chip)

        self._sense_label = QLabel()
        self._sense_label.setWordWrap(True)
        self._sense_label.setStyleSheet(
            f"QLabel {{ color: {C.SEMANTIC_COLORS['text_secondary']}; }}"
        )

        # —— ② 纠错区：字段 chips + 「划旧写新」行 + 备注 + 行内错误 ——
        chips_row = QHBoxLayout()
        chips_row.setSpacing(C.SPACING["sm"])
        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)
        self._chips: dict[str, QPushButton] = {}
        for field in C.CORRECTION_FIELDS:
            chip = QPushButton(C.CORRECTION_FIELD_LABELS.get(field, field), self)
            chip.setObjectName("fieldChip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFocusPolicy(Qt.FocusPolicy.TabFocus)
            chip.setStyleSheet(self._chip_qss())
            self._chip_group.addButton(chip)
            self._chips[field] = chip
            chips_row.addWidget(chip)
        chips_row.addStretch(1)
        first = next(iter(self._chips))
        self._chips[first].setChecked(True)
        self._chip_group.buttonClicked.connect(self._refresh_value_row)

        # 划旧写新：被纠正的旧值（删除线浅墨）紧贴新值输入框，构成 before → after
        value_row = QHBoxLayout()
        value_row.setSpacing(C.SPACING["md"])
        current_caption = QLabel(C.CORRECTION_DIALOG_CURRENT)
        current_caption.setStyleSheet(
            f"QLabel {{ color: {C.SEMANTIC_COLORS['text_faint']};"
            f" font-size: {C.FONT_SIZE['caption']}px; }}"
        )
        value_row.addWidget(current_caption)
        self._old_value_label = QLabel()
        strike_font = QFont(C.JP_BUBBLE_FONT_FAMILY)
        strike_font.setStrikeOut(True)
        self._old_value_label.setFont(strike_font)
        # 硬性限宽兜底：即使省略度量与渲染字体有漂移，也不会把输入框挤扁
        self._old_value_label.setMaximumWidth(_OLD_VALUE_MAX_W + 10)
        self._old_value_label.setStyleSheet(
            f"QLabel {{ color: {C.SEMANTIC_COLORS['text_faint']}; }}"
        )
        value_row.addWidget(self._old_value_label)
        self._value_edit = QLineEdit()
        self._value_edit.setPlaceholderText("输入正确的内容")
        value_row.addWidget(self._value_edit, 1)
        self._speaker = SpeakerButton(self)
        self._speaker.clicked.connect(self._on_preview_speaker)
        self._speaker.setVisible(False)
        value_row.addWidget(self._speaker)

        self._note_edit = QLineEdit()
        self._note_edit.setPlaceholderText(C.CORRECTION_DIALOG_NOTE_HINT)

        self._error_label = QLabel()
        self._error_label.setWordWrap(True)
        self._error_label.setStyleSheet(
            "QLabel { color: " + C.SEMANTIC_COLORS["destructive"] + ";"
            f" font-size: {C.FONT_SIZE['caption']}px; }}"
        )
        self._error_label.setVisible(False)

        # —— ③ 已有纠错（仅存在时出现，与分隔线一起显隐）——
        self._existing_box = QWidget()
        existing_layout = QVBoxLayout(self._existing_box)
        existing_layout.setContentsMargins(0, 0, 0, 0)
        existing_layout.setSpacing(C.SPACING["sm"])
        existing_title = QLabel(C.CORRECTION_DIALOG_EXISTING)
        existing_title.setStyleSheet(
            f"QLabel {{ color: {C.SEMANTIC_COLORS['text_secondary']};"
            f" font-size: {C.FONT_SIZE['caption']}px; font-weight: bold; }}"
        )
        existing_layout.addWidget(existing_title)
        self._existing_layout = QVBoxLayout()
        existing_layout.addLayout(self._existing_layout)
        self._existing_box.setVisible(False)

        # —— 动作区：右对齐，取消 ghost + 提交 primary（与应用按钮惯例一致）——
        submit_btn = QPushButton(C.CORRECTION_DIALOG_SUBMIT)
        theme.set_variant(submit_btn, "primary")
        submit_btn.setDefault(True)
        submit_btn.clicked.connect(self._on_submit)
        cancel_btn = QPushButton(C.CORRECTION_DIALOG_CANCEL)
        theme.set_variant(cancel_btn, "ghost")
        cancel_btn.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(submit_btn)

        note_caption = QLabel(C.CORRECTION_DIALOG_NOTE_LABEL)
        note_caption.setStyleSheet(
            f"QLabel {{ color: {C.SEMANTIC_COLORS['text_faint']};"
            f" font-size: {C.FONT_SIZE['caption']}px; }}"
        )

        # —— 组装：发丝线分隔三段，段间留白统一 md ——
        root = QVBoxLayout(self)
        root.setContentsMargins(
            C.SPACING["lg"], C.SPACING["lg"], C.SPACING["lg"], C.SPACING["lg"]
        )
        root.setSpacing(C.SPACING["md"])
        root.addLayout(header)
        root.addWidget(self._sense_label)
        root.addWidget(self._hairline())
        root.addLayout(chips_row)
        root.addLayout(value_row)
        root.addWidget(note_caption)
        root.addWidget(self._note_edit)
        root.addWidget(self._error_label)
        root.addWidget(self._hairline())
        root.addWidget(self._existing_box)
        root.addStretch(1)
        root.addLayout(buttons)

        self.resize(480, self.sizeHint().height())
        # 下限保护：长释义态的「划旧写新」行需要 480 宽才舒展（防外部布局压扁）
        self.setMinimumWidth(460)

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def open_for(self, entry: VocabEntry, corrections: list[CorrectionItem]) -> None:
        """按词条回填 UI（每次打开由 controller 调用，拿到最新值）。

        Args:
            entry: 待纠错词条（来自当前合并后的词库，含已生效的覆盖值）。
            corrections: 该词已有的纠错记录（可逐条撤销）。
        """

        self._entry = entry
        self._error_label.setText("")
        self._error_label.setVisible(False)
        self._note_edit.setText("")
        self._word_label.setText(entry.word)
        self._kana_label.setText(entry.kana)
        self._level_chip.setText(entry.level)
        self._sense_label.setText(f"{entry.translation}｜{entry.meaning}")
        # 字段 chips 复位到首项（表记）；刷新预填 / 删除线 / 喇叭显隐
        first_field = next(iter(self._chips))
        self._chip_group.setExclusive(False)
        for field, chip in self._chips.items():
            chip.setChecked(field == first_field)
        self._chip_group.setExclusive(True)
        self._refresh_value_row()
        self._rebuild_existing(corrections)

    # ------------------------------------------------------------------ #
    # 内部：状态
    # ------------------------------------------------------------------ #
    def _current_field(self) -> str:
        """当前勾选的纠错字段名。"""

        for field, chip in self._chips.items():
            if chip.isChecked():
                return field
        return next(iter(self._chips))

    def _current_field_value(self, field: str) -> str:
        """当前展示词条在指定字段上的值（覆盖层生效后的值）。"""

        if self._entry is None:
            return ""
        return str(getattr(self._entry, field, "") or "")

    def _refresh_value_row(self, *_args) -> None:
        """切换字段 → 删除线旧值 / 新值预填 / 试听喇叭显隐联动，并清错误提示。

        旧值**中段省略**（单行放不下长释义时保留头尾，完整值进 tooltip）：
        删除线是「改什么」的参照，不是编辑面，断行反而破坏 before → after 的
        一眼可读。
        """

        field = self._current_field()
        old_value = self._current_field_value(field)
        # 度量字体用**显式像素字号**构造：QWidget::font() 不反映 QSS 的
        # font-size（它走 style 解析），用默认点字号度量会把长释义省略得过宽、
        # 渲染时挤扁输入框。QSS font-size: 12px ⇔ setPixelSize(body)。
        metrics_font = QFont(C.JP_BUBBLE_FONT_FAMILY)
        metrics_font.setPixelSize(C.FONT_SIZE["body"])
        metrics = QFontMetrics(metrics_font)
        self._old_value_label.setText(
            metrics.elidedText(
                old_value, Qt.TextElideMode.ElideMiddle, _OLD_VALUE_MAX_W - 10
            )
        )
        self._old_value_label.setToolTip(old_value)
        self._value_edit.setText(old_value)
        self._error_label.setText("")
        self._error_label.setVisible(False)
        self._speaker.setVisible(field == "kana" and self._pronunciation is not None)

    def _on_preview_speaker(self) -> None:
        """试听**新读音**（读音字段专用）：用当前表记 + 新假名发音。"""

        if self._pronunciation is None or self._entry is None:
            return
        new_kana = self._value_edit.text().strip()
        if not new_kana:
            return
        self._pronunciation.play(self._entry.word, new_kana)

    # ------------------------------------------------------------------ #
    # 内部：已有纠错记录
    # ------------------------------------------------------------------ #
    def _rebuild_existing(self, corrections: list[CorrectionItem]) -> None:
        """重建「已有纠错」区（无记录时整段连同分隔线一起隐藏）。"""

        while self._existing_layout.count():
            row_item = self._existing_layout.takeAt(0)
            widget = row_item.widget()
            if widget is not None:
                widget.deleteLater()
        if not corrections:
            self._existing_box.setVisible(False)
            return

        faint = C.SEMANTIC_COLORS["text_faint"]
        for item in corrections:
            row = QHBoxLayout()
            row.setSpacing(C.SPACING["sm"])
            field_label = QLabel(C.CORRECTION_FIELD_LABELS.get(item.field, item.field))
            field_label.setStyleSheet(
                f"QLabel {{ color: {C.SEMANTIC_COLORS['text_secondary']}; font-weight: bold; }}"
            )
            row.addWidget(field_label)
            values = QLabel(
                f'<span style="color:{faint}; text-decoration:line-through;">'
                f"{item.old_value}</span>"
                f'&nbsp;<span style="color:{C.SEMANTIC_COLORS["text_primary"]};">→</span>&nbsp;'
                f'<span style="color:{C.SEMANTIC_COLORS["text_primary"]};">{item.new_value}</span>'
            )
            values.setTextFormat(Qt.TextFormat.RichText)
            row.addWidget(values, 1)
            undo_btn = QPushButton(C.CORRECTION_DIALOG_UNDO)
            theme.set_variant(undo_btn, "ghost")
            undo_btn.setObjectName("undoButton")
            undo_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            undo_btn.setStyleSheet(
                "QPushButton#undoButton {"
                f" padding: {C.SPACING['xs']}px {C.SPACING['md']}px;"
                f" font-size: {C.FONT_SIZE['caption']}px;"
                f" color: {C.SEMANTIC_COLORS['text_secondary']};"
                " }"
            )
            row.addWidget(undo_btn)
            row_widget = QWidget()
            row_widget.setLayout(row)
            undo_btn.clicked.connect(
                lambda _=False, i=item, w=row_widget: self._on_undo_clicked(i, w)
            )
            self._existing_layout.addWidget(row_widget)
        self._existing_box.setVisible(True)

    def _on_undo_clicked(self, item: CorrectionItem, row_widget: QWidget) -> None:
        """撤销一条已有纠错：上报 controller（删记录 + 重建词库）并移除该行。"""

        self.undo_requested.emit(item.id, item.field)
        row_widget.setParent(None)
        row_widget.deleteLater()
        if self._existing_layout.count() == 0:
            self._existing_box.setVisible(False)

    # ------------------------------------------------------------------ #
    # 内部：提交（系统确认）
    # ------------------------------------------------------------------ #
    def _on_submit(self) -> None:
        """提交：系统校验（非空 / 有变化 / 读音纯假名）→ 发 applied 并关闭。"""

        if self._entry is None:
            return
        field = self._current_field()
        new_value = self._value_edit.text().strip()

        error = ""
        if not new_value:
            error = C.CORRECTION_ERR_EMPTY
        elif new_value == self._current_field_value(field):
            error = C.CORRECTION_ERR_SAME
        elif field == "kana" and not is_pure_kana(new_value):
            error = C.CORRECTION_ERR_KANA
        if error:
            self._error_label.setText(error)
            self._error_label.setVisible(True)
            return

        self.applied.emit(
            str(self._entry.id),
            str(self._entry.word),
            field,
            new_value,
            self._note_edit.text().strip(),
        )
        self.accept()

    # ------------------------------------------------------------------ #
    # 内部：样式小件
    # ------------------------------------------------------------------ #
    @staticmethod
    def _hairline() -> QFrame:
        """1px 发丝分隔线（token 边框色；透明背景必须带选择器声明）。"""

        line = QFrame()
        line.setObjectName("hairline")
        line.setFixedHeight(1)
        line.setStyleSheet(
            "QFrame#hairline {"
            f" background-color: {C.SEMANTIC_COLORS['border']};"
            " border: none; max-height: 1px; }"
        )
        return line

    @staticmethod
    def _chip_qss() -> str:
        """字段 chip 三态 QSS：未选 = 描边浅墨，选中 = 近黑填充白字（唯一强调）。"""

        c = C.SEMANTIC_COLORS
        return (
            "QPushButton#fieldChip {"
            " background: transparent;"
            f" color: {c['text_secondary']};"
            f" border: 1px solid {c['border']};"
            f" border-radius: {C.RADIUS['sm']}px;"
                f" padding: {C.SPACING['xs']}px {C.SPACING['md']}px; }}"
            "QPushButton#fieldChip:hover {"
            f" background: {c['surface_alt']}; }}"
            "QPushButton#fieldChip:checked {"
            f" background: {c['primary']};"
            f" color: {c['surface']};"
            f" border: 1px solid {c['primary']}; }}"
            "QPushButton#fieldChip:focus {"
            f" border: 1px solid {c['text_faint']}; }}"
        )
