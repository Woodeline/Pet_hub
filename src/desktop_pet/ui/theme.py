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
- 统一圆角取 ``RADIUS["md"]``；焦点环取 ``FOCUS_RING_WIDTH_PX`` px 的 ``text_faint``
  浅灰描边（1px 轻量环；Tab 下划线线宽仍用 ``FOCUS_RING_PX``）。
- 组件通过动态属性 ``variant`` / ``role`` 选择样式块，由 :func:`set_variant` /
  :func:`set_role` 设置并触发重新抛光（unpolish/polish）。

圆角四档语义（收敛后不得再漂移）：
- **面板档** ``RADIUS["md"]`` = 8px：窗口内一切面板 / 卡片 / 按钮 / 输入框 / 对话框；
- **小元素档** ``RADIUS["sm"]`` = 6px：菜单条目 / chip / 滚动条手柄；
- **胶囊档** ``JP_BUTTON_RADIUS`` = 16px：**仅**气泡按钮条（浮层胶囊语义，唯一例外）；
- **笔直档** ``0``：文字 Tab 下划线选中态（刻意笔直，不圆角）。

token 扩展红线：``COLORS`` / ``SEMANTIC_COLORS`` / ``SPACING`` / ``FONT_SIZE`` / ``RADIUS``
五张表的**键集合**均被 ``test_design_tokens`` / ``test_static_constraints`` 全等断言守护；
新增色值或尺寸一律走**独立标量常量**（并同步 ``constants.__all__``），**禁止新增上述字典的键**。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from desktop_pet.core import constants as C

if TYPE_CHECKING:  # pragma: no cover —— 仅为类型注解，运行时不导入 Qt
    from PySide6.QtWidgets import QWidget

#: 按钮变体（与 QSS 中的 ``QPushButton[variant="…"]`` 选择器一一对应）。
#: ``success``：正向操作专用（「记住了」），三态渐变色值取自 ``SEMANTIC_COLORS``
#: 的 success 族，与学习泡泡按钮条的绿色渐变同源同款。
BUTTON_VARIANTS: Final[tuple[str, ...]] = (
    "primary", "success", "secondary", "ghost", "destructive"
)

#: 焦点环宽度（px）：1px 轻量浅灰环（``text_faint``），替代旧 2px 近黑粗框。
FOCUS_RING_WIDTH_PX: Final[int] = 1

#: Tab 选中下划线线宽（px）（历史常量名沿用；自焦点环改细后仅 Tab 下划线使用）。
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
    border: {FOCUS_RING_WIDTH_PX}px solid {c['text_faint']};
}}"""
    )

    # 每项：(常态底, 悬停底, 按下底, 文字色, 描边色)；``None`` → transparent。
    # 底色项既可以是纯色，也可以是 ``qlineargradient(…)`` 表达式（QSS 的 ``background``
    # 两者通吃）。``success``（「记住了」）取与气泡按钮条**完全同款**的三态渐变：
    # 端点 token（success_hover / success / success_pressed）与气泡的
    # jp_button_primary_hover/bg/pressed 一一映射同值（test_design_tokens 钉死），
    # 使窗口内按钮与浮层胶囊呈现同一抹绿、同一悬停/按下明暗走向。
    button_defs: dict[str, tuple[str | None, str, str, str, str | None]] = {
        "primary": (c["primary"], c["primary_hover"], c["primary_pressed"], c["surface"], c["primary"]),
        "success": (
            f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {c['success_hover']}, stop:0.5 {c['success']}, stop:1 {c['success_pressed']})",
            f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {c['success_hover']}, stop:1 {c['success']})",
            f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
            f" stop:0 {c['success']}, stop:1 {c['success_pressed']})",
            c["surface"],
            None,
        ),
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
    border: {FOCUS_RING_WIDTH_PX}px solid {c['text_faint']};
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
    border-radius: {r['md']}px;
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
    border: {FOCUS_RING_WIDTH_PX}px solid {c['text_faint']};
}}
QComboBox::drop-down {{
    border: none;
    width: {sp['lg']}px;
}}"""
    )

    # —— 分组框（台词设置对话框的 QGroupBox）：面板档圆角 + 标题让位 ——
    # 此前 QGroupBox 零 QSS → 系统默认方形边框 + 标题压线；此处对齐面板档（圆角 8 + 描边 + surface 底）。
    blocks.append(
        f"""
QGroupBox {{
    background: {c['surface']};
    border: 1px solid {c['border']};
    border-radius: {r['md']}px;
    margin-top: {fs['caption']}px;
    padding-top: {sp['sm']}px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: {sp['sm']}px;
    padding: 0 {sp['xs']}px;
    color: {c['text_secondary']};
    font-weight: bold;
    font-size: {fs['caption']}px;
}}"""
    )

    # —— 多行文本编辑（台词设置对话框的 QPlainTextEdit）：对齐 QComboBox/QLineEdit 四态 ——
    # 此前零 QSS → 直角系统边框，与单行输入（圆角 8 + token 色）不同族。
    blocks.append(
        f"""
QPlainTextEdit, QTextEdit {{
    background: {c['surface']};
    color: {c['text_primary']};
    border: 1px solid {c['border']};
    border-radius: {r['md']}px;
    padding: {sp['xs']}px {sp['sm']}px;
}}
QPlainTextEdit:hover, QTextEdit:hover {{
    border: 1px solid {c['text_secondary']};
}}
QPlainTextEdit:focus, QTextEdit:focus {{
    border: {FOCUS_RING_WIDTH_PX}px solid {c['text_faint']};
}}
QPlainTextEdit:disabled, QTextEdit:disabled {{
    background: {c['surface_alt']};
    color: {c['text_faint']};
}}"""
    )

    # —— 对话框面板：surface 底 + 正文色（QMessageBox 保底见下）——
    blocks.append(
        f"""
QDialog {{
    background: {c['surface']};
    color: {c['text_primary']};
}}"""
    )

    # —— QMessageBox 保底（防御性兜底）：当前仓库已无 QMessageBox 调用方 ——
    # 本批次起业务确认弹窗统一走 ui.confirm_dialog.ConfirmDialog（清空生词本已切换）；
    # 此块仅为「防未来回归系统方角 + 系统色外观」的兜底，无现存使用方。
    blocks.append(
        f"""
QMessageBox {{
    background: {c['surface']};
}}
QMessageBox QLabel {{
    color: {c['text_primary']};
}}
QMessageBox QPushButton {{
    border-radius: {r['md']}px;
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


def build_menu_qss() -> str:
    """右键菜单（托盘菜单 + 子菜单）的 Win11 风格 QSS（token 拼装，可无头单测）。

    配合 :class:`ui.menu_shadow.ShadowMenu` 使用：面板（白色圆角矩形 + 1px 描边）
    由 ShadowMenu 自绘，本 QSS 只负责把**窗口**设为透明并留出阴影留白
    （``padding = MENU_SHADOW_BAND_PX + 面板内边距``），再定义条目/分隔线样式。

    刻意**不**声明 ``QMenu::indicator`` / ``::right-arrow``：勾选标记与子菜单箭头
    交由底层原生样式绘制，避免样式表接管后勾选消失（托盘的开关/单选项依赖它）。
    """

    c = C.SEMANTIC_COLORS
    sp = C.SPACING
    r = C.RADIUS
    inset = C.MENU_SHADOW_BAND_PX + sp["xs"]

    return f"""
QMenu {{
    background: transparent;
    border: none;
    padding: {inset}px;
}}
QMenu::item {{
    padding: {sp['sm']}px {sp['xl']}px {sp['sm']}px {sp['md']}px;
    border-radius: {r['sm']}px;
}}
QMenu::item:selected {{
    background: {c['surface_alt']};
}}
QMenu::item:disabled {{
    color: {c['text_faint']};
}}
QMenu::separator {{
    height: 1px;
    background: {c['border']};
    margin-left: {sp['md']}px;
    margin-right: {sp['md']}px;
    margin-top: {sp['xs']}px;
    margin-bottom: {sp['xs']}px;
}}"""


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
    "FOCUS_RING_WIDTH_PX",
    "build_qss",
    "build_menu_qss",
    "apply_theme",
    "set_variant",
    "set_role",
    "set_card_selected",
]
