"""界面统一批次 1+2 —— 样式层 / 行为层**独立**验证（QA）。

方案依据：``docs/design-vocab-ui-unification.md`` §3（统一标准）/ §5（批次 1-2）/ §7（红线）。

本文件刻意与工程实现解耦：期望值一律写字面量或独立常量（**不做自引用式断言**），
每条断言都落在**真实渲染结果**或 ``build_qss()`` 生成字符串上，避免「实现与测试共用
同一常量」的假绿，也避免「函数存在即通过」的粗粒度检查。

覆盖：
- B 样式层：新增 QSS 块齐备、``QPlainTextEdit/QTextEdit`` 四态、卡片圆角 8≠12、
  新块无裸 hex（token 拼装）；
- C 行为层：``ConfirmDialog``（主题 / 非 frameless / 变体 / ``ask`` 两分支）、
  ``VocabWindow``（无 ``QMessageBox`` + 清空确认两条分支）、``LogWindow``（ghost 关闭
  按钮点击行为）、``BubbleTextDialog``（应用 primary / 取消 ghost + 无局部样式）、
  记录卡片三态渲染；
- D 缺陷验证：``_STATUS_COLOR_KEYS[unprocessed]`` 映射可达性（见文末）。
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLabel, QPushButton

from desktop_pet.core import constants as C
from desktop_pet.core.daily_log_store import DailyLogEntry
from desktop_pet.core.vocab_store import VocabItem
from desktop_pet.ui import theme
from desktop_pet.ui.bubble_text_dialog import BubbleTextDialog
from desktop_pet.ui.confirm_dialog import ConfirmDialog
from desktop_pet.ui.log_window import LogWindow, _LogCard
from desktop_pet.ui.vocab_window import VocabWindow

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")

#: 本批次新增/变更的样式块选择器（空白归一化后）。
_NEW_STYLE_SELECTORS: tuple[str, ...] = (
    "QGroupBox",
    "QGroupBox::title",
    "QPlainTextEdit, QTextEdit",
    "QPlainTextEdit:hover, QTextEdit:hover",
    "QPlainTextEdit:focus, QTextEdit:focus",
    "QPlainTextEdit:disabled, QTextEdit:disabled",
    "QDialog",
    "QMessageBox",
    "QMessageBox QLabel",
    "QMessageBox QPushButton",
)


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _qss_blocks(qss: str) -> dict[str, str]:
    """把 QSS 拆成「选择器 → 规则体」映射（选择器空白归一化）。"""

    blocks: dict[str, str] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", qss):
        blocks[" ".join(selector.split())] = body
    return blocks


def _semantic_hex_set() -> set[str]:
    """``SEMANTIC_COLORS`` 全部色值（大写），用于「无裸 hex」判定。"""

    return {value.upper() for value in C.SEMANTIC_COLORS.values()}


def _label_with_text(widget, text: str) -> QLabel | None:
    """在 ``widget`` 的子孙中查找文本等于 ``text`` 的 ``QLabel``（找不到返回 None）。"""

    for label in widget.findChildren(QLabel):
        if label.text() == text:
            return label
    return None


def _log_entry(i: int, status: str, day: str = "2025-01-01") -> DailyLogEntry:
    return DailyLogEntry(
        id=f"n5-{i:04d}",
        level="N5",
        word=f"語{i}",
        kana="かな",
        translation="译",
        shown_at=f"{day}T00:00:0{i}Z",
        status=status,
    )


def _vocab_item(i: int, level: str = "N5") -> VocabItem:
    return VocabItem(
        id=f"{level.lower()}-{i:04d}",
        level=level,
        word=f"語{i}",
        kana="かな",
        translation="译",
        meaning="义",
        added_at="2025-01-01T00:00:00Z",
    )


# ========================================================================== #
# B. 样式层证明（可执行断言）
# ========================================================================== #
def test_build_qss_contains_new_unified_selectors() -> None:
    """新增 8 个选择器块必须齐备（``build_qss()`` 原文字符串断言）。"""

    qss = theme.build_qss()
    for selector in (
        "QGroupBox",
        "QGroupBox::title",
        "QPlainTextEdit",
        "QTextEdit",
        "QDialog",
        "QMessageBox",
        "QMessageBox QLabel",
        "QMessageBox QPushButton",
    ):
        assert selector in qss, f"缺少选择器：{selector}"


def test_qplaintext_edit_has_four_states() -> None:
    """``QPlainTextEdit / QTextEdit`` 具备常态 + hover + focus + disabled 四态（按块断言）。"""

    blocks = _qss_blocks(theme.build_qss())
    base = "QPlainTextEdit, QTextEdit"
    assert base in blocks, f"缺少多行输入基础块：{base}"
    assert blocks[base].strip(), "多行输入基础块规则体为空"

    states = (
        ("QPlainTextEdit:hover, QTextEdit:hover", "border"),
        ("QPlainTextEdit:focus, QTextEdit:focus", "border"),
        ("QPlainTextEdit:disabled, QTextEdit:disabled", "background"),
    )
    for selector, marker in states:
        assert selector in blocks, f"缺少状态块：{selector}"
        assert marker in blocks[selector], f"{selector} 缺少 {marker} 属性"


def test_card_role_radius_equals_md_not_lg() -> None:
    """卡片 role 圆角 == ``RADIUS['md']``(8) 且 != ``RADIUS['lg']``(12)。

    期望值写**字面量 8 / 12**（非 ``C.RADIUS[...]`` 自引用），避免实现与测试共用常量的假绿。
    """

    assert "border-radius: 8px" in _qss_blocks(theme.build_qss())['QFrame[role="card"]']
    assert "border-radius: 12px" not in _qss_blocks(theme.build_qss())['QFrame[role="card"]']


def test_new_style_blocks_use_tokens_not_bare_hex() -> None:
    """新增样式块的色值只能来自 ``SEMANTIC_COLORS``，尺寸只能来自 ``RADIUS``（token 拼装）。

    依赖既有 ``test_static_constraints.test_ui_has_no_bare_hex_color_literals`` 的
    AST 守护兜底（源码级），此处再从生成字符串侧做一次交叉验证。
    """

    blocks = _qss_blocks(theme.build_qss())
    allowed = _semantic_hex_set()
    for selector in _NEW_STYLE_SELECTORS:
        assert selector in blocks, f"缺少新增样式块：{selector}"
        found = {m.group(0).upper() for m in _HEX_RE.finditer(blocks[selector])}
        offenders = found - allowed
        assert not offenders, f"{selector} 出现非 token 裸色值：{sorted(offenders)}"

    # 逐块点检关键 token 值确实被引用（防「块存在但空壳」）。
    c = C.SEMANTIC_COLORS
    assert c["surface"] in blocks["QGroupBox"]
    assert c["border"] in blocks["QGroupBox"]
    assert f"border-radius: {C.RADIUS['md']}px" in blocks["QGroupBox"]
    assert c["text_secondary"] in blocks["QGroupBox::title"]
    assert c["surface"] in blocks["QPlainTextEdit, QTextEdit"]
    assert c["text_primary"] in blocks["QDialog"]
    assert c["surface"] in blocks["QMessageBox"]
    assert c["text_primary"] in blocks["QMessageBox QLabel"]
    assert f"border-radius: {C.RADIUS['md']}px" in blocks["QMessageBox QPushButton"]


def test_four_radius_tiers_match_spec_and_are_distinct() -> None:
    """四档圆角语义（方案 §3.2）：面板 8 / 小元素 6 / 胶囊 16 / Tab 0，且互不相等。"""

    assert C.RADIUS["md"] == 8
    assert C.RADIUS["sm"] == 6
    assert C.JP_BUTTON_RADIUS == 16
    tiers = {C.RADIUS["md"], C.RADIUS["sm"], C.JP_BUTTON_RADIUS, 0}
    assert len(tiers) == 4, f"四档圆角出现重复值：{tiers}"
    # Tab 刻意笔直：border-radius 0。
    assert "border-radius: 0" in _qss_blocks(theme.build_qss())['QPushButton[variant="tab"]']


# ========================================================================== #
# C. 行为层证明（pytest-qt / 离屏）
# ========================================================================== #
# ---- ConfirmDialog ---- #
def test_confirm_dialog_applies_theme(qtbot) -> None:
    """``ConfirmDialog`` 的 stylesheet 等于生成器输出（与其它窗口同源）。"""

    dialog = ConfirmDialog("标题", "正文", "确认")
    qtbot.addWidget(dialog)
    assert dialog.styleSheet() == theme.build_qss()


def test_confirm_dialog_is_not_frameless(qtbot) -> None:
    """形态约定（§8 D3）：**不设** ``FramelessWindowHint``。"""

    dialog = ConfirmDialog("标题", "正文", "确认")
    qtbot.addWidget(dialog)
    assert not (dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)


def test_confirm_dialog_button_variants(qtbot) -> None:
    """[取消] = ghost、[确认] = destructive，且按钮为 ``QPushButton``。"""

    dialog = ConfirmDialog("标题", "正文", "清空…")
    qtbot.addWidget(dialog)
    assert dialog._cancel_btn.property("variant") == "ghost"
    assert dialog._confirm_btn.property("variant") == "destructive"
    assert isinstance(dialog._cancel_btn, QPushButton)
    assert isinstance(dialog._confirm_btn, QPushButton)


def test_confirm_dialog_buttons_are_wired(qtbot) -> None:
    """[确认] 点击 → ``Accepted``；[取消] 点击 → ``Rejected``（真实按钮接线，非 mock）。"""

    confirm_dlg = ConfirmDialog("t", "x", "ok")
    qtbot.addWidget(confirm_dlg)
    confirm_dlg._confirm_btn.click()
    assert confirm_dlg.result() == int(QDialog.DialogCode.Accepted)

    cancel_dlg = ConfirmDialog("t", "x", "ok")
    qtbot.addWidget(cancel_dlg)
    cancel_dlg._cancel_btn.click()
    assert cancel_dlg.result() == int(QDialog.DialogCode.Rejected)


def test_confirm_dialog_ask_confirm_path_returns_true(qtbot, monkeypatch) -> None:
    """``ask`` 确认分支：走「确认按钮 → accept」真实接线后返回 ``True``。"""

    def _fake_exec(self) -> int:
        self._confirm_btn.click()
        return self.result()

    monkeypatch.setattr(ConfirmDialog, "exec", _fake_exec)
    assert ConfirmDialog.ask(None, "标题", "正文", "清空…") is True


def test_confirm_dialog_ask_cancel_path_returns_false(qtbot, monkeypatch) -> None:
    """``ask`` 取消分支：走「取消按钮 → reject」真实接线后返回 ``False``。"""

    def _fake_exec(self) -> int:
        self._cancel_btn.click()
        return self.result()

    monkeypatch.setattr(ConfirmDialog, "exec", _fake_exec)
    assert ConfirmDialog.ask(None, "标题", "正文", "清空…") is False


# ---- VocabWindow ---- #
def test_vocab_window_source_has_no_qmessagebox(src_root) -> None:
    """源码级：``vocab_window.py`` 全文不再出现 ``QMessageBox``（整串断言，非 count 计数）。

    注：必须断言**完整字符串**而非 ``count()``——注释 / docstring 里的同名字样
    会打破计数式断言的稳定性。
    """

    source = (src_root / "ui" / "vocab_window.py").read_text(encoding="utf-8")
    assert "QMessageBox" not in source


def test_vocab_clear_confirm_rejected_emits_nothing(qtbot, monkeypatch) -> None:
    """清空确认被取消（``ask`` → False）→ ``clear_requested`` **不**发出。"""

    from desktop_pet.ui import vocab_window as vw

    monkeypatch.setattr(vw.ConfirmDialog, "ask", staticmethod(lambda *a, **k: False))
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([_vocab_item(1)])

    emitted: list[int] = []
    window.clear_requested.connect(lambda: emitted.append(1))
    window._on_clear_clicked()
    assert emitted == []


def test_vocab_clear_confirm_accepted_emits(qtbot, monkeypatch) -> None:
    """清空确认通过（``ask`` → True）→ ``clear_requested`` 发出一次。"""

    from desktop_pet.ui import vocab_window as vw

    monkeypatch.setattr(vw.ConfirmDialog, "ask", staticmethod(lambda *a, **k: True))
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([_vocab_item(1)])

    emitted: list[int] = []
    window.clear_requested.connect(lambda: emitted.append(1))
    window._on_clear_clicked()
    assert emitted == [1]


def test_vocab_clear_confirm_not_shown_when_empty(qtbot, monkeypatch) -> None:
    """空生词本点「清空」直接返回，不弹确认框（``ask`` 不得被调用）。"""

    from desktop_pet.ui import vocab_window as vw

    calls: list[tuple] = []

    def _spy(*args, **kwargs):
        calls.append(args)
        return True

    monkeypatch.setattr(vw.ConfirmDialog, "ask", staticmethod(_spy))
    window = VocabWindow()
    qtbot.addWidget(window)  # 无 refresh → 空
    window._on_clear_clicked()
    assert calls == []


# ---- LogWindow 关闭按钮 ---- #
def test_log_window_close_button_ghost_with_icon(qtbot) -> None:
    """底栏右侧「关闭」按钮存在、ghost 变体、文案走独立标量、挂有可渲染图标。"""

    window = LogWindow()
    qtbot.addWidget(window)
    button = window._btn_close
    assert button.text() == C.JP_LOG_BTN_CLOSE
    assert button.property("variant") == "ghost"
    assert not button.icon().isNull(), "关闭按钮未挂图标"
    assert button.iconSize().width() == C.SPACING["lg"]
    assert button.iconSize().height() == C.SPACING["lg"]


def test_log_window_close_button_closes_window(qtbot) -> None:
    """点击「关闭」→ 窗口不可见（真实点击，非只看信号接线）。

    注入 ``reduce_motion=True`` 跳过淡出动画，直接走默认 close —— 离屏环境下避免
    动画时序不确定性；被测行为（按钮 → close）不受影响。
    """

    window = LogWindow()
    qtbot.addWidget(window)
    window.set_reduce_motion(True)
    window.show()
    qtbot.waitUntil(window.isVisible)
    qtbot.mouseClick(window._btn_close, Qt.MouseButton.LeftButton)
    assert window.isVisible() is False


# ---- BubbleTextDialog ---- #
def test_bubble_text_dialog_action_variants(qtbot) -> None:
    """「应用」= primary、「取消」= ghost（按文本定位按钮，不依赖局部变量）。"""

    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    buttons = {b.text(): b for b in dialog.findChildren(QPushButton)}
    assert "应用" in buttons and "取消" in buttons
    assert buttons["应用"].property("variant") == "primary"
    assert buttons["取消"].property("variant") == "ghost"


def test_bubble_text_dialog_source_has_no_local_stylesheet(src_root) -> None:
    """源码级：``bubble_text_dialog.py`` 不再写局部 ``setStyleSheet``（样式统一走 theme）。"""

    source = (src_root / "ui" / "bubble_text_dialog.py").read_text(encoding="utf-8")
    assert "setStyleSheet" not in source


# ---- LogWindow 记录卡片三态 ---- #
def test_log_card_mastered_and_vocab_render_status_labels(qtbot) -> None:
    """已掌握 / 生词卡片渲染状态标签，颜色分别命中 ``info`` / ``warning``。"""

    mastered = _LogCard(_log_entry(1, C.DAILY_LOG_STATUS_MASTERED))
    qtbot.addWidget(mastered)
    label = _label_with_text(mastered, C.JP_LOG_STATUS_MASTERED)
    assert label is not None, "已掌握卡片缺少状态标签"
    assert C.SEMANTIC_COLORS["info"] in label.styleSheet()

    vocab = _LogCard(_log_entry(2, C.DAILY_LOG_STATUS_VOCAB))
    qtbot.addWidget(vocab)
    label = _label_with_text(vocab, C.JP_LOG_STATUS_VOCAB)
    assert label is not None, "生词卡片缺少状态标签"
    assert C.SEMANTIC_COLORS["warning"] in label.styleSheet()


def test_log_window_cards_built_for_three_states(qtbot) -> None:
    """窗口级：三种状态各一条时卡片均被构建（id 全在）。"""

    window = LogWindow()
    qtbot.addWidget(window)
    entries = [
        _log_entry(1, C.DAILY_LOG_STATUS_MASTERED),
        _log_entry(2, C.DAILY_LOG_STATUS_VOCAB),
        _log_entry(3, C.DAILY_LOG_STATUS_UNPROCESSED),
    ]
    window.refresh("2025-01-01", entries, 15)
    assert set(window._card_by_id) == {"n5-0001", "n5-0002", "n5-0003"}


# ========================================================================== #
# D. 缺陷验证：未处理态状态色映射可达性
# ========================================================================== #
def test_unprocessed_card_renders_contrast_status_label(qtbot) -> None:
    """[回归守护] 未处理卡片必须渲染「未处理」状态标签，且其颜色为 ``text_secondary``。

    方案 §3.1 目标：E2 的「未处理」文字色由 ``muted``(#98A2AD) 提升为 ``text_secondary``
    (#5A626C) 以提对比（WCAG 2.59 → 6.18）。

    历史（本用例曾作为**有意失败**的缺陷证据）：
    - 第一轮实现只在 ``_STATUS_COLOR_KEYS`` 里改了未处理态的取值，而 ``_LogCard.__init__``
      存在 ``if entry.status != C.DAILY_LOG_STATUS_UNPROCESSED:`` 门控 → 未处理态**根本不建标签**，
      映射永不参与渲染（死改动，§3.1 目标未达成）。
    - 裁决：**三态齐平**（删除门控，三种状态一律渲染标签），而非删映射降低口径。

    现修复已落地：门控删除，``log_window.py`` 三态统一经 ``_STATUS_COLOR_KEYS.get(status)`` 取色建标签。
    **本条断言不得再被改弱**——它守的是「有实现且真的到达渲染路径」，不是「常量写对了」。
    """

    card = _LogCard(_log_entry(3, C.DAILY_LOG_STATUS_UNPROCESSED))
    qtbot.addWidget(card)
    status_label = _label_with_text(card, C.JP_LOG_STATUS_UNPROCESSED)
    assert status_label is not None, (
        "未处理卡片未渲染状态标签 → _STATUS_COLOR_KEYS[UNPROCESSED] 不可达"
        "（log_window.py:88 分支排除未处理态），方案 §3.1 目标未达成"
    )
    assert C.SEMANTIC_COLORS["text_secondary"] in status_label.styleSheet(), (
        f"未处理状态标签色应为 text_secondary({C.SEMANTIC_COLORS['text_secondary']})"
    )


def test_unprocessed_contrast_is_improved_over_muted() -> None:
    """量化对比度：``text_secondary``(#5A626C) 相对 ``surface``(#FFFFFF) 对比度须高于 ``muted``(#98A2AD)。

    该断言只证明「若采用 text_secondary 则对比度确会提升」，用于量化 §3.1 的取值合理性；
    它与上条「是否真的采用了」相互独立。
    """

    def _relative_luminance(hex_color: str) -> float:
        raw = hex_color.lstrip("#")
        channels = [int(raw[i : i + 2], 16) / 255.0 for i in (0, 2, 4)]

        def _linear(c: float) -> float:
            return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4

        r, g, b = (_linear(c) for c in channels)
        return 0.2126 * r + 0.7152 * g + 0.0722 * b

    def _contrast(fg: str, bg: str) -> float:
        l1, l2 = _relative_luminance(fg), _relative_luminance(bg)
        hi, lo = max(l1, l2), min(l1, l2)
        return (hi + 0.05) / (lo + 0.05)

    surface = C.SEMANTIC_COLORS["surface"]
    muted = C.SEMANTIC_COLORS["muted"]
    secondary = C.SEMANTIC_COLORS["text_secondary"]
    assert muted == C.SEMANTIC_COLORS["text_faint"], "muted 应与 text_faint 同值（方案 §3.1）"
    assert _contrast(secondary, surface) > _contrast(muted, surface), (
        "text_secondary 未比 muted 具备更高对比度"
    )
