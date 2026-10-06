"""工程师自测：ui.data_window —— 数据管理窗口（信号路由与展示）。

窗口为纯信号源：不做文件 IO / 业务判定。断言仅针对 UI 状态与信号。
"""

from __future__ import annotations

import pytest

from desktop_pet.core import constants as C
from desktop_pet.ui.data_window import DataWindow


def _button_by_text(window: DataWindow, text: str):
    for button in window.findChildren(type(window._btn_close)):
        if button.text() == text:
            return button
    return None


def test_buttons_emit_signals(qtbot) -> None:
    """四张动作卡点击 → 对应信号各发一次（弹框在 controller 槽里，单测不接槽）。"""

    window = DataWindow()
    qtbot.addWidget(window)

    anki_button = _button_by_text(window, C.DATA_BTN_ANKI)
    csv_button = _button_by_text(window, C.DATA_BTN_CSV)
    backup_button = _button_by_text(window, C.DATA_BTN_BACKUP)
    restore_button = _button_by_text(window, C.DATA_BTN_RESTORE)
    assert all(b is not None for b in (anki_button, csv_button, backup_button, restore_button))

    with qtbot.waitSignal(window.anki_export_requested, timeout=2000):
        anki_button.click()
    with qtbot.waitSignal(window.csv_export_requested, timeout=2000):
        csv_button.click()
    with qtbot.waitSignal(window.backup_export_requested, timeout=2000):
        backup_button.click()
    with qtbot.waitSignal(window.backup_import_requested, timeout=2000):
        restore_button.click()


def test_set_data_dir_updates_label(qtbot) -> None:
    """数据目录标签随 set_data_dir 更新。"""

    window = DataWindow()
    qtbot.addWidget(window)
    window.set_data_dir(r"C:\Users\me\AppData\Roaming\desktop-pet")
    assert "desktop-pet" in window._path_label.text()


def test_paint_smoke(qtbot) -> None:
    """整窗渲染冒烟。"""

    window = DataWindow()
    qtbot.addWidget(window)
    window.resize(C.DATA_WINDOW_W, C.DATA_WINDOW_H)
    window.set_data_dir("C:\\somewhere")
    assert not window.grab().isNull()
