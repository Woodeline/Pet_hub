"""业务窗口统一精修（标题带 + token 内边距 + 点缀色全覆盖）回归测试。

守护 2026-11-12「窗口一并优化」落地的不变式：

- 新标量 WINDOW_TITLE_PX 为正整数且同步 __all__；build_qss 含 window_title 角色。
- WindowHeader：标题 / 说明角色正确、语义图标非空、DPR 感知。
- polish_root：根布局内边距 / 间距统一取 token（左右 lg / 上下 md / 间距 md）。
- 七个窗口（生词本 / 已掌握 / 记录 / 统计 / 数据 / 词库 / 气泡文案）首行为
  WindowHeader，根布局已 token 化。
- 三个对话框补齐 set_accent；ConfirmDialog.ask 继承父窗口点缀色。

全部使用 ``QT_QPA_PLATFORM=offscreen``（conftest 强制）。
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QDialog, QVBoxLayout, QWidget

from desktop_pet.core import constants as C
from desktop_pet.ui import theme
from desktop_pet.ui.bank_window import BankWindow
from desktop_pet.ui.bubble_text_dialog import BubbleTextDialog
from desktop_pet.ui.confirm_dialog import ConfirmDialog
from desktop_pet.ui.correction_dialog import CorrectionDialog
from desktop_pet.ui.data_window import DataWindow
from desktop_pet.ui.log_window import LogWindow
from desktop_pet.ui.mastered_window import MasteredWindow
from desktop_pet.ui.stats_window import StatsWindow
from desktop_pet.ui.vocab_window import VocabWindow
from desktop_pet.ui.window_chrome import WindowHeader, polish_root

_ACCENT = "#B85C1E"


def test_window_title_scalar_exported() -> None:
    assert isinstance(C.WINDOW_TITLE_PX, int) and C.WINDOW_TITLE_PX > 0
    assert "WINDOW_TITLE_PX" in C.__all__
    assert f"font-size: {C.WINDOW_TITLE_PX}px" in theme.build_qss()
    assert 'QLabel[role="window_title"]' in theme.build_qss()


def test_window_header_roles_and_icon(qtbot) -> None:
    header = WindowHeader("生词本", "收藏的单词", "bookmark")
    qtbot.addWidget(header)
    labels = header.findChildren(QWidget)
    roles = {w.property("role") for w in labels if w.property("role")}
    assert "window_title" in roles and "caption" in roles
    pixmaps = [w.pixmap() for w in labels if hasattr(w, "pixmap") and w.pixmap() and not w.pixmap().isNull()]
    assert pixmaps, "语义图标未渲染"


def test_polish_root_token_margins(qtbot) -> None:
    host = QWidget()
    qtbot.addWidget(host)
    layout = QVBoxLayout(host)
    polish_root(layout)
    sp = C.SPACING
    assert layout.contentsMargins().left() == sp["lg"]
    assert layout.contentsMargins().right() == sp["lg"]
    assert layout.contentsMargins().top() == sp["md"]
    assert layout.contentsMargins().bottom() == sp["md"]
    assert layout.spacing() == sp["md"]


@pytest.mark.parametrize(
    "factory",
    [VocabWindow, MasteredWindow, LogWindow, StatsWindow, DataWindow, BankWindow,
     BubbleTextDialog],
)
def test_windows_have_header_and_token_root(qtbot, factory) -> None:
    window = factory()
    qtbot.addWidget(window)
    root = window.layout()
    assert root is not None
    sp = C.SPACING
    margins = root.contentsMargins()
    assert (margins.left(), margins.top(), margins.right(), margins.bottom()) == (
        sp["lg"], sp["md"], sp["lg"], sp["md"]
    ), f"{factory.__name__} 根布局内边距未 token 化"
    first = root.itemAt(0).widget()
    assert isinstance(first, WindowHeader), f"{factory.__name__} 首行非标题带"


@pytest.mark.parametrize(
    "factory", [BubbleTextDialog, CorrectionDialog]
)
def test_dialogs_accept_accent(qtbot, factory) -> None:
    dialog = factory()
    qtbot.addWidget(dialog)
    dialog.set_accent(_ACCENT)
    assert _ACCENT in dialog.styleSheet(), f"{factory.__name__} 点缀色未进 QSS"


def test_confirm_dialog_accent_and_inheritance(qtbot, monkeypatch) -> None:
    dialog = ConfirmDialog("标题", "正文", "确认", accent=_ACCENT)
    qtbot.addWidget(dialog)
    assert _ACCENT in dialog.styleSheet()

    captured: dict = {}

    def fake_exec(self):
        captured["dlg"] = self
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", fake_exec)
    parent = QWidget()
    qtbot.addWidget(parent)
    parent._accent = _ACCENT
    assert ConfirmDialog.ask(parent, "标题", "正文", "确认") is True
    assert _ACCENT in captured["dlg"].styleSheet(), "ask 未继承父窗口点缀色"

def test_header_stays_tight_when_window_tall(qtbot) -> None:
    """窗口加高时标题带不拉伸、标题/说明不被撑开（2026-11-12 布局缺陷回归）。"""

    from PySide6.QtWidgets import QApplication, QLabel

    window = VocabWindow()
    qtbot.addWidget(window)
    window.resize(560, 600)
    window.show()
    QApplication.processEvents()
    header = window.findChildren(WindowHeader)[0]
    assert header.height() == header.sizeHint().height(), "标题带被根布局拉伸"
    labels = [l for l in header.findChildren(QLabel) if l.text()]
    title, caption = labels[0], labels[1]
    assert caption.y() - (title.y() + title.height()) <= 2, "标题与说明被撑开大缝隙"


def test_data_window_content_fits_default_size(qtbot) -> None:
    """默认尺寸下底栏关闭按钮完整落在窗口内（不裁切）。"""

    from desktop_pet.ui.data_window import DataWindow as DW

    window = DW()
    qtbot.addWidget(window)
    window.resize(C.DATA_WINDOW_W, C.DATA_WINDOW_H)
    window.show()
    from PySide6.QtWidgets import QApplication

    QApplication.processEvents()
    buttons = [b for b in window.findChildren(type(window._btn_close)) if b.text() == C.STATS_BTN_CLOSE]
    assert buttons, "未找到关闭按钮"
    geo = buttons[0].geometry()
    assert geo.bottom() <= window.height(), f"关闭按钮越界：{geo} vs {window.height()}"
