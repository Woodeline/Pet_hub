"""ui.theme —— token → QSS 的**唯一翻译层**（UI 视觉升级 P1）。

职责边界：
- 本模块是**唯一**把 ``core.constants`` 里的 design token（``SEMANTIC_COLORS`` /
  ``SPACING`` / ``FONT_SIZE`` / ``RADIUS``）翻译成 Qt 样式表（QSS）字符串的地方。
  组件层（三个窗口）只调用本模块，**禁止**在组件里再写裸十六进制色值。
- ``build_qss()`` 是**纯字符串拼装**，不触达任何 Qt 对象，因此**无需 QApplication 实例**
  即可调用（便于单元测试直接断言字符串内容）。
- QSS 中出现的每一个 ``#RRGGBB`` 都必须来自 :data:`SEMANTIC_COLORS` 的某个值；
  需要透明一律用 ``transparent`` 关键字，不写 hex。

设计约束（对应计划 §3 / §0 红线）：
- 尺寸（内边距 / 圆角 / 字号）只能来自 ``SPACING`` / ``FONT_SIZE`` / ``RADIUS``。
- 统一圆角取 ``RADIUS["md"]``；焦点环取 ``FOCUS_RING_PX`` px 的 ``primary`` 描边。
- 组件通过动态属性 ``variant`` / ``role`` 选择样式块，由 :func:`set_variant` /
  :func:`set_role` 设置并触发重新抛光（unpolish/polish）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from desktop_pet.core import constants as C

if TYPE_CHECKING:  # pragma: no cover —— 仅为类型注解，运行时不导入 Qt
    from PySide6.QtWidgets import QWidget

#: 按钮变体（与 QSS 中的 ``QPushButton[variant="…"]`` 选择器一一对应）。
BUTTON_VARIANTS: Final[tuple[str, ...]] = ("primary", "secondary", "ghost", "destructive")

#: 焦点环宽度（px），参与 QSS 中 ``:focus`` 描边的拼装。
FOCUS_RING_PX: Final[int] = 2


def _repolish(widget: "QWidget") -> None:
    """让动态属性变更（``variant`` / ``role``）立即生效：unpolish → polish → update。"""

    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def build_qss(accent: str | None = None) -> str:
    """由 design token 拼出全局 QSS 字符串（不含任何裸十六进制，除 token 值本身）。

    Args:
        accent: 主题点缀色（``#RRGGBB``）；``None`` 时全部用中性主色。点缀色只影响
            **小面积元素**——Tab 选中文字/下划线与卡片选中描边，其余保持近黑。
    """

    c = C.SEMANTIC_COLORS
    sp = C.SPACING
    fs = C.FONT_SIZE
    r = C.RADIUS
    radius_md = r["md"]
    accent_color = accent if accent else c["primary"]

    blocks: list[str] = []

    # —— 基础：窗口底色 / 正文色 / 基准字号 / 统一字体 ——
    blocks.append(
        f"""
QWidget {{
    background: {c['surface']};
    color: {c['text_primary']};
    font-family: "Microsoft YaHei";
    font-size: {fs['body']}px;
}}
QToolTip {{
    background: {c['surface_alt']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    padding: {sp['xs']}px {sp['sm']}px;
}}"""
    )

    # —— 按钮四变体 × 四态（hover / pressed / disabled / focus）——
    # 基础兜底：无显式 ``variant`` 的 QPushButton 取「secondary 中性外观 + 四态」。
    # 变体选择器带属性 → 特异性高于基础规则，会正确覆盖，无需 !important。
    blocks.append(
        f"""
QPushButton {{
    background: {c['surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: {radius_md}px;
    padding: {sp['sm']}px {sp['lg']}px;
}}
QPushButton:hover {{
    background: {c['surface_alt']};
}}
QPushButton:pressed {{
    background: {c['border']};
}}
QPushButton:disabled {{
    background: {c['surface_alt']};
    color: {c['text_faint']};
    border: 1px solid {c['border']};
}}
QPushButton:focus {{
    border: {FOCUS_RING_PX}px solid {c['primary']};
}}"""
    )

    # 每项：(常态底, 悬停底, 按下底, 文字色, 描边色)；``None`` → transparent。
    button_defs: dict[str, tuple[str | None, str, str, str, str | None]] = {
        "primary": (c["primary"], c["primary_hover"], c["primary_pressed"], c["surface"], c["primary"]),
        "secondary": (c["surface"], c["surface_alt"], c["border"], c["text_primary"], c["border"]),
        "ghost": (None, c["surface_alt"], c["border"], c["text_primary"], None),
        "destructive": (c["destructive"], c["destructive_hover"], c["destructive"], c["surface"], c["destructive"]),
    }
    for variant in BUTTON_VARIANTS:
        bg, hover, pressed, text, border = button_defs[variant]
        bg = bg or "transparent"
        border = border or "transparent"
        blocks.append(
            f"""
QPushButton[variant="{variant}"] {{
    background: {bg};
    color: {text};
    border: 1px solid {border};
    border-radius: {radius_md}px;
    padding: {sp['sm']}px {sp['lg']}px;
}}
QPushButton[variant="{variant}"]:hover {{
    background: {hover};
}}
QPushButton[variant="{variant}"]:pressed {{
    background: {pressed};
}}
QPushButton[variant="{variant}"]:disabled {{
    background: {c['surface_alt']};
    color: {c['text_faint']};
    border: 1px solid {c['border']};
}}
QPushButton[variant="{variant}"]:focus {{
    border: {FOCUS_RING_PX}px solid {c['primary']};
}}"""
        )

    # —— 标签语义角色：chip（中性描边胶囊）/ caption（次级说明文字）——
    blocks.append(
        f"""
QLabel[role="chip"] {{
    background: transparent;
    color: {c['text_secondary']};
    border: 1px solid {c['border']};
    border-radius: {r['sm']}px;
    padding: {sp['xs']}px {sp['sm']}px;
}}
QLabel[role="caption"] {{
    color: {c['text_secondary']};
    font-size: {fs['caption']}px;
}}"""
    )

    # —— 卡片（词条列表 / 详情分组）：圆角面板 + 悬停微高亮 + 选中描边 ——
    # 选中态经动态属性 ``selected``（QFrame 无 :selected 伪类），由
    # :func:`set_card_selected` 触发重新抛光。
    blocks.append(
        f"""
QFrame[role="card"] {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r['lg']}px;
}}
QFrame[role="card"]:hover {{
    background: {c['surface_alt']};
}}
QFrame[role="card"][selected="true"] {{
    background: {c['surface_alt']};
    border: 1px solid {accent_color};
}}"""
    )

    # —— 文字 Tab（词条列表顶部筛选，参考移动端词典应用）——
    # 选中态 = 点缀色文字 + 底部短横线；未选中为次级色无边框平铺。
    blocks.append(
        f"""
QPushButton[variant="tab"] {{
    background: transparent;
    color: {c['text_secondary']};
    border: none;
    border-bottom: {FOCUS_RING_PX}px solid transparent;
    border-radius: 0;
    padding: {sp['xs']}px {sp['md']}px;
    font-weight: bold;
}}
QPushButton[variant="tab"]:hover {{
    color: {c['text_primary']};
    background: transparent;
}}
QPushButton[variant="tab"]:checked {{
    color: {accent_color};
    border-bottom: {FOCUS_RING_PX}px solid {accent_color};
    background: transparent;
}}
QPushButton[variant="tab"]:focus {{
    border-bottom: {FOCUS_RING_PX}px solid {accent_color};
    color: {accent_color};
}}"""
    )

    # —— 表格：斑马纹 / hover / 选中 / 表头 ——
    blocks.append(
        f"""
QTableWidget {{
    background: {c['surface']};
    alternate-background-color: {c['surface_alt']};
    gridline-color: {c['border']};
    border: 1px solid {c['border']};
    border-radius: {radius_md}px;
    selection-background-color: {c['primary']};
    selection-color: {c['surface']};
}}
QTableWidget::item {{
    padding: {sp['xs']}px {sp['sm']}px;
}}
QTableWidget::item:alternate {{
    background: {c['surface_alt']};
}}
QTableWidget::item:hover {{
    background: {c['border']};
}}
QTableWidget::item:selected {{
    background: {c['primary']};
    color: {c['surface']};
}}
QHeaderView::section {{
    background: {c['surface_alt']};
    color: {c['text_primary']};
    border: none;
    border-bottom: 1px solid {c['border']};
    padding: {sp['xs']}px {sp['sm']}px;
    font-weight: bold;
}}"""
    )

    # —— 输入类控件：下拉框 / 单行输入 ——
    blocks.append(
        f"""
QComboBox, QLineEdit {{
    background: {c['surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: {radius_md}px;
    padding: {sp['xs']}px {sp['sm']}px;
}}
QComboBox:hover, QLineEdit:hover {{
    border: 1px solid {c['text_secondary']};
}}
QComboBox:focus, QLineEdit:focus {{
    border: {FOCUS_RING_PX}px solid {c['primary']};
}}
QComboBox::drop-down {{
    border: none;
    width: {sp['lg']}px;
}}"""
    )

    # —— 滚动条：细窄、无箭头 ——
    blocks.append(
        f"""
QScrollBar:vertical {{
    background: {c['surface_alt']};
    width: {sp['md']}px;
    margin: 0;
    border-radius: {r['sm']}px;
}}
QScrollBar::handle:vertical {{
    background: {c['border']};
    min-height: {sp['lg']}px;
    border-radius: {r['sm']}px;
}}
QScrollBar::handle:vertical:hover {{
    background: {c['text_faint']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: transparent;
}}"""
    )

    return "\n".join(blocks)


def apply_theme(widget: "QWidget", accent: str | None = None) -> None:
    """把全局 QSS 应用到 ``widget``（通常是一个顶层窗口）。

    Args:
        widget: 目标窗口。
        accent: 主题点缀色；``None`` 用中性主色（见 :func:`build_qss`）。
    """

    widget.setStyleSheet(build_qss(accent))


def set_variant(widget: "QWidget", variant: str) -> None:
    """设置按钮的 ``variant`` 动态属性并重新抛光，使 QSS 选择器立即生效。"""

    widget.setProperty("variant", variant)
    _repolish(widget)


def set_role(widget: "QWidget", role: str) -> None:
    """设置控件的 ``role`` 动态属性并重新抛光（用于 ``QLabel[role="chip"]`` 等）。"""

    widget.setProperty("role", role)
    _repolish(widget)


def set_card_selected(widget: "QWidget", selected: bool) -> None:
    """切换卡片（``QFrame[role="card"]``）的 ``selected`` 动态属性并重新抛光。"""

    widget.setProperty("selected", bool(selected))
    _repolish(widget)


__all__ = [
    "BUTTON_VARIANTS",
    "FOCUS_RING_PX",
    "build_qss",
    "apply_theme",
    "set_variant",
    "set_role",
    "set_card_selected",
]
