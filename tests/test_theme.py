"""ui.theme（token → QSS 生成器）回归测试。

守护 P1 的核心不变式：

- ``build_qss()`` 是**纯字符串**产物，**无需 QApplication 即可调用**（子进程验证）。
- QSS 命中关键选择器：按钮四变体 × 四态、chip、斑马纹、滚动条、输入框。
- QSS 里出现的**每一个** ``#RRGGBB`` 都来自 ``SEMANTIC_COLORS`` 的值（无裸 hex）。
- 统一圆角命中 ``RADIUS["md"]``；焦点环为 ``FOCUS_RING_WIDTH_PX``=1px 的 ``text_faint`` 浅灰（Tab 下划线线宽仍为 ``FOCUS_RING_PX``=2）。
- ``apply_theme`` / ``set_variant`` / ``set_role`` 行为契约。
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

from desktop_pet.core import constants as C
from desktop_pet.ui import theme

_HEX_RE = re.compile(r"#[0-9A-Fa-f]{6}")


def _semantic_hex_set() -> set[str]:
    """``SEMANTIC_COLORS`` 的全部色值（统一大写，便于与 QSS 提取结果比较）。"""

    return {value.upper() for value in C.SEMANTIC_COLORS.values()}


def _qss_blocks(qss: str) -> dict[str, str]:
    """把 QSS 拆成「选择器 → 规则体」映射（选择器空白归一化）。

    这样可按块边界断言，避免退化为「全文子串包含」的粗粒度检查。
    """

    blocks: dict[str, str] = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", qss):
        blocks[" ".join(selector.split())] = body
    return blocks


#: 四态选择器后缀 → 该块内必须出现的属性关键字。
_STATE_MARKERS: tuple[tuple[str, str], ...] = (
    (":hover", "background"),
    (":pressed", "background"),
    (":disabled", "background"),
    (":focus", "border"),
)


# --------------------------------------------------------------------------- #
# 1. 基本契约 + 不依赖 QApplication
# --------------------------------------------------------------------------- #
def test_build_qss_returns_nonempty_str() -> None:
    """``build_qss()`` 返回非空字符串。"""

    qss = theme.build_qss()
    assert isinstance(qss, str)
    assert qss.strip(), "build_qss() 返回空字符串"


def test_build_qss_needs_no_qapplication(project_root) -> None:
    """在**全新子进程**中导入 theme 并调用 build_qss —— 全程不得加载 PySide6。"""

    code = (
        "import sys\n"
        "from desktop_pet.ui import theme\n"
        "loaded = [m for m in sys.modules if m.startswith('PySide6')]\n"
        "assert not loaded, 'theme 导入过程加载了 Qt: %r' % loaded\n"
        "qss = theme.build_qss()\n"
        "assert isinstance(qss, str) and qss.strip()\n"
        "print('QSS_OK', len(qss))\n"
    )
    env = {**os.environ, "PYTHONPATH": str(project_root / "src")}
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=env, timeout=60
    )
    assert result.returncode == 0, f"子进程调用 build_qss 失败：{result.stderr}"
    assert "QSS_OK" in result.stdout


# --------------------------------------------------------------------------- #
# 2. 关键选择器齐备
# --------------------------------------------------------------------------- #
def test_qss_button_variants_have_all_four_states() -> None:
    """每个按钮变体**逐一**具备 :hover/:pressed/:disabled/:focus 四块（按块断言）。

    抓「某个变体缺某一态」（例如 ghost 漏了 :disabled）这类细粒度缺失。
    """

    blocks = _qss_blocks(theme.build_qss())
    for variant in theme.BUTTON_VARIANTS:
        base = f'QPushButton[variant="{variant}"]'
        assert base in blocks, f"缺少变体基础块：{base}"
        assert blocks[base].strip(), f"{base} 规则体为空"
        for state, marker in _STATE_MARKERS:
            selector = f"{base}{state}"
            assert selector in blocks, f"缺少状态块：{selector}"
            assert marker in blocks[selector], f"{selector} 缺少 {marker} 属性"


def test_qss_base_button_has_all_four_states() -> None:
    """无 variant 的基础 ``QPushButton`` 兜底块同样具备四态。"""

    blocks = _qss_blocks(theme.build_qss())
    assert "QPushButton" in blocks, "缺少基础 QPushButton 兜底块"
    assert blocks["QPushButton"].strip(), "基础 QPushButton 规则体为空"
    for state, marker in _STATE_MARKERS:
        selector = f"QPushButton{state}"
        assert selector in blocks, f"缺少基础按钮状态块：{selector}"
        assert marker in blocks[selector], f"{selector} 缺少 {marker} 属性"


def test_qss_contains_required_selectors() -> None:
    """chip / caption / 斑马纹 / 表头 / 输入控件 / 滚动条选择器齐备。"""

    qss = theme.build_qss()
    for selector in (
        'QLabel[role="chip"]',
        'QLabel[role="caption"]',
        "QTableWidget",
        "QTableWidget::item:alternate",
        "QTableWidget::item:hover",
        "QTableWidget::item:selected",
        "QHeaderView::section",
        "QComboBox",
        "QLineEdit",
        "QScrollBar:vertical",
    ):
        assert selector in qss, f"缺少选择器：{selector}"


# --------------------------------------------------------------------------- #
# 3. 无裸 hex：QSS 中所有色值都来自 SEMANTIC_COLORS
# --------------------------------------------------------------------------- #
def test_qss_hex_values_all_from_semantic_colors() -> None:
    """QSS 中出现的每个 ``#RRGGBB`` 都必须是 ``SEMANTIC_COLORS`` 的某个值。"""

    found = {m.group(0).upper() for m in _HEX_RE.finditer(theme.build_qss())}
    allowed = _semantic_hex_set()
    offenders = found - allowed
    assert not offenders, f"QSS 出现非 token 裸色值：{sorted(offenders)}"
    assert found, "QSS 未包含任何色值（拼装可能出错）"


def test_qss_uses_semantic_colors_actually() -> None:
    """QSS 确实引用了语义色表里的多个色值（非空壳实现）。"""

    qss = theme.build_qss()
    used = {v.upper() for v in C.SEMANTIC_COLORS.values() if v.upper() in qss.upper()}
    assert len(used) >= 8, f"引用到的语义色过少：{sorted(used)}"


# --------------------------------------------------------------------------- #
# 4. 圆角 / 焦点环
# --------------------------------------------------------------------------- #
def test_qss_radius_hits_radius_md() -> None:
    """统一圆角命中 ``RADIUS["md"]``（期望值用**字面量 8**，避免自引用假绿）。"""

    assert "border-radius: 8px" in theme.build_qss(), "未使用 RADIUS['md']=8 作为统一圆角"


def test_qss_focus_ring_uses_focus_px_and_primary() -> None:
    """焦点环为 ``1px solid #98A2AD``（text_faint 浅灰轻量环；期望值用**字面量**避免自引用假绿）。

    Tab 选中下划线线宽不受影响（``FOCUS_RING_PX``=2 继续用于 ``border-bottom``）。
    """

    qss = theme.build_qss()
    assert "border: 1px solid #98A2AD" in qss, "焦点环未按契约（1px + text_faint 浅灰）拼装"
    assert "border: 2px solid #1F2328" not in qss, "旧 2px 近黑焦点环残留"
    assert "border: 1px solid #4C8DDA" not in qss, "淡蓝焦点环残留（已改浅灰）"
    assert "border-bottom: 2px solid transparent" in qss, "Tab 下划线线宽被误改"


# --------------------------------------------------------------------------- #
# 5. apply_theme / set_variant / set_role 行为
# --------------------------------------------------------------------------- #
def test_set_variant_sets_property(qtbot) -> None:
    """``set_variant`` 写入动态属性且值为传入值。"""

    from PySide6.QtWidgets import QPushButton

    btn = QPushButton("x")
    qtbot.addWidget(btn)
    theme.set_variant(btn, "primary")
    assert btn.property("variant") == "primary"


def test_set_role_sets_property(qtbot) -> None:
    """``set_role`` 写入 ``role`` 动态属性。"""

    from PySide6.QtWidgets import QLabel

    label = QLabel("x")
    qtbot.addWidget(label)
    theme.set_role(label, "chip")
    assert label.property("role") == "chip"


def test_apply_theme_sets_stylesheet(qtbot) -> None:
    """``apply_theme`` 使窗口 stylesheet 等于 ``build_qss()``。"""

    from PySide6.QtWidgets import QWidget

    widget = QWidget()
    qtbot.addWidget(widget)
    theme.apply_theme(widget)
    assert widget.styleSheet() == theme.build_qss()
    assert widget.styleSheet().strip(), "apply_theme 设置了空样式"


# --------------------------------------------------------------------------- #
# 6. 三个业务窗口确已接入 theme + 卡片列表使用统一卡片样式
# --------------------------------------------------------------------------- #
def test_business_windows_apply_theme(qtbot) -> None:
    """``VocabWindow`` / ``LogWindow`` / ``WordDetailWindow`` 的 stylesheet 均等于生成器输出。

    防「窗口忘了加 ``theme.apply_theme`` 调用」的静默回归。
    """

    from desktop_pet.ui.log_window import LogWindow
    from desktop_pet.ui.vocab_window import VocabWindow
    from desktop_pet.ui.word_detail_window import WordDetailWindow

    expected = theme.build_qss()
    for window_cls in (VocabWindow, LogWindow, WordDetailWindow):
        window = window_cls()
        qtbot.addWidget(window)
        assert window.styleSheet() == expected, f"{window_cls.__name__} 未接入 theme"


def test_build_qss_contains_card_and_tab_styles() -> None:
    """卡片化改版：QSS 必须包含卡片 / 文字 Tab / 状态角色的样式块。"""

    qss = theme.build_qss()
    assert 'QFrame[role="card"]' in qss
    assert 'QFrame[role="card"][selected="true"]' in qss
    assert 'QPushButton[variant="tab"]' in qss
    assert 'QPushButton[variant="tab"]:checked' in qss


# --------------------------------------------------------------------------- #
# 7. 主题点缀色（accent）：仅 Tab 选中 / 卡片选中描边响应
# --------------------------------------------------------------------------- #
def test_build_qss_accent_colors_tab_and_card_selection() -> None:
    """accent 非空时 Tab 选中与卡片选中描边使用点缀色，其余规则不变。"""

    neutral = theme.build_qss()
    accent_qss = theme.build_qss("#B85C1E")

    assert "color: #B85C1E" in accent_qss
    assert "border: 1px solid #B85C1E" in accent_qss
    # 中性版不含该点缀色
    assert "#B85C1E" not in neutral


def test_apply_theme_with_accent_updates_window_stylesheet(qtbot) -> None:
    """窗口 set_accent 后 stylesheet 等于带点缀色的生成器输出。"""

    from desktop_pet.ui.vocab_window import VocabWindow

    window = VocabWindow()
    qtbot.addWidget(window)
    assert window.styleSheet() == theme.build_qss()  # 初始中性
    window.set_accent("#4A9DC6")
    assert window.styleSheet() == theme.build_qss("#4A9DC6")


# --------------------------------------------------------------------------- #
# 8. build_menu_qss：右键菜单 Win11 风格（配合 ui.menu_shadow.ShadowMenu）
# --------------------------------------------------------------------------- #
def test_build_menu_qss_transparent_window_with_band_padding() -> None:
    """窗口块必须透明、无边框，padding = 阴影留白 + 面板内边距（留出自绘阴影区）。"""

    blocks = _qss_blocks(theme.build_menu_qss())
    assert "QMenu" in blocks, "缺少 QMenu 窗口块"
    body = blocks["QMenu"]
    assert "transparent" in body, "窗口背景必须透明（面板由 ShadowMenu 自绘）"
    expected_padding = C.MENU_SHADOW_BAND_PX + C.SPACING["xs"]
    assert f"padding: {expected_padding}px" in body, "padding 应等于 MENU_SHADOW_BAND_PX + 面板内边距"


def test_build_menu_qss_item_and_separator_styles() -> None:
    """条目（常态/悬停/禁用）与分隔线选择器齐备。"""

    blocks = _qss_blocks(theme.build_menu_qss())
    for selector in ("QMenu::item", "QMenu::item:selected", "QMenu::item:disabled", "QMenu::separator"):
        assert selector in blocks, f"缺少选择器：{selector}"
    assert C.SEMANTIC_COLORS["surface_alt"] in blocks["QMenu::item:selected"]
    assert C.SEMANTIC_COLORS["text_faint"] in blocks["QMenu::item:disabled"]


def test_build_menu_qss_does_not_override_indicator() -> None:
    """不声明 indicator / right-arrow：勾选标记与子菜单箭头交由原生样式绘制。"""

    qss = theme.build_menu_qss()
    assert "indicator" not in qss, "接管 indicator 会导致托盘勾选标记消失"
    assert "right-arrow" not in qss, "接管 right-arrow 会导致子菜单箭头消失"


def test_build_menu_qss_hex_values_all_from_semantic_colors() -> None:
    """菜单 QSS 中所有 ``#RRGGBB`` 均来自 ``SEMANTIC_COLORS``。"""

    found = {m.group(0).upper() for m in _HEX_RE.finditer(theme.build_menu_qss())}
    allowed = _semantic_hex_set()
    assert found, "菜单 QSS 中未发现任何色值（样式缺失？）"
    assert found <= allowed, f"出现非法色值：{found - allowed}"
