"""工程师自测：ui.bank_window —— 词库管理窗口（卡片 / 信号 / 空态）。

窗口为纯信号源：文件操作与合并全在 controller。断言针对 UI 状态与信号；
删除流程的二次确认由 ConfirmDialog 承担（测试中以替身放行 / 拒绝）。
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QCheckBox, QPushButton

from desktop_pet.core import constants as C
from desktop_pet.core.bank_registry import BankInfo
from desktop_pet.ui.bank_window import BankWindow
from desktop_pet.ui import confirm_dialog


def _info(bank_id: str, name: str, *, enabled: bool = True, builtin: bool = False, count: int = 10) -> BankInfo:
    return BankInfo(
        id=bank_id,
        name=name,
        enabled=enabled,
        builtin=builtin,
        word_count=count,
        level_counts={"N5": count},
    )


def _card_widgets(window: BankWindow) -> list:
    return [
        window._cards_layout.itemAt(i).widget()
        for i in range(window._cards_layout.count())
        if window._cards_layout.itemAt(i).widget() is not None
    ]


def _checkbox_of(card) -> QCheckBox:
    boxes = card.findChildren(QCheckBox)
    assert boxes, "导入库卡片应有启用勾选"
    return boxes[0]


def _button_by_text(parent, text: str) -> QPushButton:
    for button in parent.findChildren(QPushButton):
        if button.text() == text:
            return button
    raise AssertionError(f"未找到按钮：{text}")


def test_refresh_renders_builtin_and_imported_cards(qtbot) -> None:
    """内置库首行固定；导入库渲染启停勾选；状态栏计数正确。"""

    window = BankWindow()
    qtbot.addWidget(window)
    infos = [
        _info("", C.BANK_BUILTIN_LABEL, builtin=True, count=8000),
        _info("bk-a", "导入库A", enabled=True, count=120),
        _info("bk-b", "导入库B", enabled=False, count=30),
    ]
    window.refresh(infos, 8150)

    assert len(_card_widgets(window)) == 3
    assert window._status_label.text() == "共 8150 个词 · 1/2 个词库启用"
    assert not window._empty_label.isVisibleTo(window)
    # 内置库卡无启用勾选
    builtin_card = _card_widgets(window)[0]
    assert builtin_card.findChildren(QCheckBox) == []


def test_refresh_empty_shows_hint(qtbot) -> None:
    """无导入库：空态提示可见。"""

    window = BankWindow()
    qtbot.addWidget(window)
    window.refresh([_info("", C.BANK_BUILTIN_LABEL, builtin=True, count=2)], 2)
    assert window._empty_label.isVisibleTo(window)


def test_toggle_signal_carries_id_and_state(qtbot) -> None:
    """勾选启停 → toggle_requested 携带 (bank_id, enabled)。"""

    window = BankWindow()
    qtbot.addWidget(window)
    window.refresh([_info("bk-a", "导入库A", count=5)], 5)
    card = _card_widgets(window)[0]

    with qtbot.waitSignal(window.toggle_requested, timeout=2000) as blocker:
        _checkbox_of(card).setChecked(False)
    assert blocker.args == ["bk-a", False]


def test_delete_confirmed_emits_signal(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    """删除：确认框放行 → delete_requested 携带 bank_id。"""

    window = BankWindow()
    qtbot.addWidget(window)
    window.refresh([_info("bk-a", "导入库A", count=5)], 5)
    card = _card_widgets(window)[0]

    monkeypatch.setattr(
        confirm_dialog.ConfirmDialog, "ask", staticmethod(lambda *a, **k: True)
    )
    with qtbot.waitSignal(window.delete_requested, timeout=2000) as blocker:
        _button_by_text(card, "删除").click()
    assert blocker.args == ["bk-a"]


def test_delete_cancelled_emits_nothing(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    """删除确认框取消：不发删除信号。"""

    window = BankWindow()
    qtbot.addWidget(window)
    window.refresh([_info("bk-a", "导入库A", count=5)], 5)
    card = _card_widgets(window)[0]

    monkeypatch.setattr(
        confirm_dialog.ConfirmDialog, "ask", staticmethod(lambda *a, **k: False)
    )
    received: list[str] = []
    window.delete_requested.connect(received.append)
    _button_by_text(card, "删除").click()
    assert received == []


def test_paint_smoke(qtbot) -> None:
    """整窗渲染冒烟。"""

    window = BankWindow()
    qtbot.addWidget(window)
    window.resize(C.BANK_WINDOW_W, C.BANK_WINDOW_H)
    window.refresh(
        [
            _info("", C.BANK_BUILTIN_LABEL, builtin=True, count=100),
            _info("bk-a", "导入库A", count=20),
        ],
        120,
    )
    assert not window.grab().isNull()
