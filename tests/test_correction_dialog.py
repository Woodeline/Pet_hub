"""工程师自测：纠错对话框 —— 提交校验（系统确认）与 applied / undo_requested 信号。

覆盖：
1. 新值与当前值相同 → 行内错误、不关窗、不发 applied。
2. 读音字段非纯假名（拉丁字母 / 汉字）→ 行内错误、不关窗。
3. 合法读音 → 发 applied（id / word / field / new_value / note 齐全）并关窗。
4. 空值 → 行内错误。
5. 已有纠错记录的「撤销」按钮 → 发 undo_requested 并移除该行。

QT_QPA_PLATFORM=offscreen（conftest），窗口可见性断言在该平台下有效。
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from desktop_pet.core import constants as C
from desktop_pet.core.corrections_store import CorrectionItem
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.ui.correction_dialog import CorrectionDialog

_ISO_T0 = "2025-01-01T00:00:00Z"


def _entry() -> VocabEntry:
    return VocabEntry(
        id="n5-0001",
        level="N5",
        word="語",
        kana="かな",
        translation="译",
        meaning="义",
    )


def _existing() -> list[CorrectionItem]:
    return [
        CorrectionItem(
            id="n5-0001",
            word="語",
            field="translation",
            old_value="译",
            new_value="翻译",
            created_at=_ISO_T0,
        )
    ]


@pytest.fixture()
def dlg(qapp: QApplication) -> CorrectionDialog:
    """带一条已有纠错记录的对话框（已 open_for 词条）。"""

    dialog = CorrectionDialog()
    dialog.open_for(_entry(), _existing())
    return dialog


def _select_kana(dlg: CorrectionDialog) -> None:
    """切到「读音」字段（点击字段 chip，触发新值预填当前假名）。"""

    dlg._chips["kana"].click()
    assert dlg._chips["kana"].isChecked()
    assert not dlg._chips["word"].isChecked()


def test_same_value_rejected(dlg: CorrectionDialog) -> None:
    """新值与当前值相同：行内错误、窗口不关、不发 applied。"""

    captured: list[tuple] = []
    dlg.applied.connect(lambda *args: captured.append(args))
    _select_kana(dlg)
    dlg.show()

    dlg._on_submit()

    assert dlg.isVisible()
    assert dlg._error_label.isVisible()
    assert dlg._error_label.text() == C.CORRECTION_ERR_SAME
    assert captured == []
    dlg.close()


def test_non_kana_reading_rejected(dlg: CorrectionDialog) -> None:
    """读音字段填拉丁字母：行内错误提示纯假名要求，不发 applied。"""

    captured: list[tuple] = []
    dlg.applied.connect(lambda *args: captured.append(args))
    _select_kana(dlg)
    dlg._value_edit.setText("kana")
    dlg.show()

    dlg._on_submit()

    assert dlg.isVisible()
    assert dlg._error_label.text() == C.CORRECTION_ERR_KANA
    assert captured == []
    dlg.close()


def test_kanji_reading_rejected(dlg: CorrectionDialog) -> None:
    """读音字段填汉字（熟字训按字面）：同样被纯假名校验拒绝。"""

    _select_kana(dlg)
    dlg._value_edit.setText("明日")
    dlg.show()

    dlg._on_submit()

    assert dlg.isVisible()
    assert dlg._error_label.text() == C.CORRECTION_ERR_KANA
    dlg.close()


def test_valid_reading_emits_applied_and_closes(dlg: CorrectionDialog) -> None:
    """合法新读音：发 applied（五个字段齐全，含备注）并关窗。"""

    captured: list[tuple] = []
    dlg.applied.connect(lambda *args: captured.append(args))
    _select_kana(dlg)
    dlg._value_edit.setText("かなー")
    dlg._note_edit.setText("某词典")
    dlg.show()

    dlg._on_submit()

    assert not dlg.isVisible()
    assert captured == [("n5-0001", "語", "kana", "かなー", "某词典")]


def test_empty_value_rejected(dlg: CorrectionDialog) -> None:
    """清空新值：行内错误「新值不能为空」。"""

    _select_kana(dlg)
    dlg._value_edit.setText("  ")
    dlg.show()

    dlg._on_submit()

    assert dlg.isVisible()
    assert dlg._error_label.text() == C.CORRECTION_ERR_EMPTY
    dlg.close()


def test_word_field_accepts_kanji_value(dlg: CorrectionDialog) -> None:
    """表记字段（word）不做假名校验：汉字新值可直接提交。"""

    captured: list[tuple] = []
    dlg.applied.connect(lambda *args: captured.append(args))
    dlg._value_edit.setText("語2")
    dlg.show()

    dlg._on_submit()

    assert not dlg.isVisible()
    assert captured == [("n5-0001", "語", "word", "語2", "")]


def test_undo_button_emits_signal_and_removes_row(dlg: CorrectionDialog) -> None:
    """已有纠错记录的「撤销」：发 undo_requested(id, field) 并移除该行。"""

    captured: list[tuple] = []
    dlg.undo_requested.connect(lambda item_id, field: captured.append((item_id, field)))
    dlg.show()
    assert dlg._existing_box.isVisible()

    undo_buttons = [
        btn for btn in dlg.findChildren(QPushButton) if btn.text() == C.CORRECTION_DIALOG_UNDO
    ]
    assert len(undo_buttons) == 1
    undo_buttons[0].click()

    assert captured == [("n5-0001", "translation")]
    assert not dlg._existing_box.isVisible()
    dlg.close()
