"""ui.bubble_text_dialog —— 情绪气泡台词设置对话框（预设台词包 + 两组自定义台词）。

职责边界（对齐 ui 层其它业务窗口）：

- 只做「选择与编辑」的 UI，业务判定在 ``app.controller``：确定时经
  :attr:`applied` 信号交回 ``(pack, auto_texts, keyboard_texts)``，由 controller
  写配置并持久化；
- **不触碰单词泡泡**：本对话框只影响 ``controller._show_bubble_for`` 的台词来源，
  ``BubbleWindow.show_word`` 及日语学习模块零关联；
- 生效无需重启：controller 每次弹情绪气泡都现读 ``cfg``，对话框确认即生效。

**两组自定义池（2026-09-26 需求 C）——触发来源与显示规则**：

+--------------+------------------------------------------+--------------------------+
| 台词来源     | 触发来源                                 | 键盘关键字约束           |
+==============+==========================================+==========================+
| 预设台词包   | 两组自定义池为空时由该组回落使用         | 自动侧过滤（见下）       |
+--------------+------------------------------------------+--------------------------+
| 自动触发组   | 自动闲聊（**每 20 秒~1 分钟随机一条**）/ | **含键盘关键字的行被过滤** |
|              | 情绪自然变化 / 休息时打呵欠 /            | 即永不被自动触发         |
|              | 鼠标移到宠物上（悬停、点击，立即显示）   |                          |
+--------------+------------------------------------------+--------------------------+
| 敲击键盘组   | 仅真实敲击键盘时（打字、按任意键；       | 不过滤                   |
|              | 独立的 20 秒~1 分钟随机节奏，不刷屏）    |                          |
+--------------+------------------------------------------+--------------------------+

「键盘关键字」= ``C.BUBBLE_KEYBOARD_KEYWORDS``（键盘 / 敲 / 打字 / 码字 / 手速 / 按键）。
把键盘文案写进自动触发组不会报错，但那几行只会被静默过滤；想让它生效请移到敲击键盘组。

编辑约定：两组自定义池**均为一行一条**；非空行 strip、去空、去重、限长
（上限见 ``C.BUBBLE_TEXT_CUSTOM_MAX_*``，真正的清洗在
``core.config._coerce_bubble_texts_custom``，此处预览计数做同样规则）。
某一组非空即优先于预设包；清空该组编辑区 = 该组回落预设包。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)

from desktop_pet.core import constants as C
from desktop_pet.ui import theme

logger = logging.getLogger(__name__)

__all__ = ["BubbleTextDialog"]


class BubbleTextDialog(QDialog):
    """情绪气泡台词设置对话框（模态）。

    用法（controller 单例持有）::

        dlg = BubbleTextDialog(
            cfg.bubble_text_pack,
            cfg.bubble_texts_custom,
            cfg.bubble_texts_custom_keyboard,
        )
        dlg.applied.connect(self._on_bubble_text_applied)
        dlg.show()
    """

    #: 确认应用：(预设包名, 自动触发组台词, 敲击键盘组台词)——均为清洗后的最终值
    applied = Signal(str, list, list)

    def __init__(
        self,
        pack: str = C.DEFAULT_BUBBLE_TEXT_PACK,
        custom_texts: list[str] | None = None,
        custom_keyboard_texts: list[str] | None = None,
        parent=None,
    ) -> None:
        """构造对话框并回填当前配置。

        Args:
            pack: 当前预设台词包名。
            custom_texts: 当前**自动触发组**自定义台词（空 = 该组未配置）。
            custom_keyboard_texts: 当前**敲击键盘组**自定义台词（空 = 该组未配置）。
            parent: Qt 父对象。
        """

        super().__init__(parent)
        self.setWindowTitle(C.APP_DISPLAY_NAME + " · 气泡文案")
        self.setModal(False)
        theme.apply_theme(self)

        self._pack_combo = QComboBox()
        for name in ("default", C.BUBBLE_TEXT_PACK_ENERGY, C.BUBBLE_TEXT_PACK_GENTLE):
            self._pack_combo.addItem(self._pack_label(name), name)
        self._pack_combo.setCurrentText(self._pack_label(str(pack or "default")))

        # —— 自动触发组 ——
        self._auto_edit = QPlainTextEdit()
        self._auto_edit.setPlaceholderText(
            "自动触发组的台词：一行一条（留空 = 使用上方预设台词包）\n"
            f"最多 {C.BUBBLE_TEXT_CUSTOM_MAX_COUNT} 条，每条最长 "
            f"{C.BUBBLE_TEXT_CUSTOM_MAX_LEN} 字。\n"
            "示例：\n摸摸我呀~\n加油鸭！"
        )
        self._auto_edit.setPlainText("\n".join(custom_texts or []))
        self._auto_edit.textChanged.connect(self._update_counts)

        self._auto_count_label = QLabel()
        self._auto_count_label.setWordWrap(True)

        # —— 敲击键盘组 ——
        self._hit_edit = QPlainTextEdit()
        self._hit_edit.setPlaceholderText(
            "敲击键盘组的台词：一行一条（留空 = 敲击时使用预设台词包）\n"
            "示例：\n键盘敲得真快！\n哒哒哒，我听着你敲呢~"
        )
        self._hit_edit.setPlainText("\n".join(custom_keyboard_texts or []))
        self._hit_edit.textChanged.connect(self._update_counts)

        self._hit_count_label = QLabel()
        self._hit_count_label.setWordWrap(True)

        self._update_counts()

        apply_btn = QPushButton("应用")
        cancel_btn = QPushButton("取消")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply)
        cancel_btn.clicked.connect(self.reject)

        pack_box = QGroupBox("预设台词包")
        pack_layout = QVBoxLayout(pack_box)
        pack_layout.addWidget(QLabel("某一组自定义台词为空时，该组回落到此内置风格："))
        pack_layout.addWidget(self._pack_combo)

        auto_box = QGroupBox("自定义台词 · 自动触发组")
        auto_layout = QVBoxLayout(auto_box)
        auto_layout.addWidget(
            QLabel(
                "触发来源：自动闲聊（每 20 秒~1 分钟随机一条）、情绪变化、休息时打呵欠、"
                "鼠标移到宠物上（立即显示一条）。"
            )
        )
        auto_layout.addWidget(self._auto_edit)
        auto_layout.addWidget(self._auto_count_label)

        hit_box = QGroupBox("自定义台词 · 敲击键盘组")
        hit_layout = QVBoxLayout(hit_box)
        hit_layout.addWidget(
            QLabel(
                "触发来源：仅当你真实敲击键盘时（打字、按任意键）；"
                "独立 20 秒~1 分钟随机节奏，打字再快也不刷屏。"
            )
        )
        hit_layout.addWidget(self._hit_edit)
        hit_layout.addWidget(self._hit_count_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(apply_btn)

        root = QVBoxLayout(self)
        root.addWidget(pack_box)
        root.addWidget(auto_box)
        root.addWidget(hit_box)
        root.addLayout(buttons)

        self.resize(460, 620)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def load_state(
        self,
        pack: str,
        custom_texts: list[str],
        custom_keyboard_texts: list[str] | None = None,
    ) -> None:
        """按当前配置回填 UI（重开对话框时由 controller 调用，拿到最新值）。"""

        self._pack_combo.setCurrentText(self._pack_label(str(pack or "default")))
        self._auto_edit.setPlainText("\n".join(custom_texts or []))
        self._hit_edit.setPlainText("\n".join(custom_keyboard_texts or []))
        self._update_counts()

    @staticmethod
    def _pack_label(name: str) -> str:
        """台词包名 → 菜单显示文案。"""

        labels = {
            "default": "默认（原版台词）",
            C.BUBBLE_TEXT_PACK_ENERGY: "元气满满",
            C.BUBBLE_TEXT_PACK_GENTLE: "温柔治愈",
        }
        return labels.get(name, name)

    @staticmethod
    def parse_custom_texts(raw: str) -> list[str]:
        """把编辑区文本解析为清洗后的台词列表（一行一条，规则与 config coerce 一致）。

        **两组共用**本方法：清洗规则与组别无关，只有触发来源与关键字门控不同。
        """

        cleaned: list[str] = []
        for line in raw.splitlines():
            text = line.strip()
            if not text or text in cleaned:
                continue
            cleaned.append(text[: C.BUBBLE_TEXT_CUSTOM_MAX_LEN])
            if len(cleaned) >= C.BUBBLE_TEXT_CUSTOM_MAX_COUNT:
                break
        return cleaned

    def _update_counts(self) -> None:
        """实时刷新两组计数（与 config 清洗规则一致 + 自动组关键字过滤提示）。"""

        auto = self.parse_custom_texts(self._auto_edit.toPlainText())
        if auto:
            blocked = sum(1 for t in auto if C.has_keyboard_keyword(t))
            text = f"已启用自动触发：{len(auto)} 条"
            if blocked:
                text += (
                    f"｜其中 {blocked} 条含键盘关键字，不会被自动触发"
                    "（如需生效请移到敲击键盘组）"
                )
            self._auto_count_label.setText(text)
        else:
            self._auto_count_label.setText("未启用（自动触发时使用上方预设台词包）")

        hit = self.parse_custom_texts(self._hit_edit.toPlainText())
        if hit:
            self._hit_count_label.setText(f"已启用敲击触发：{len(hit)} 条（仅敲键盘时出现）")
        else:
            self._hit_count_label.setText("未启用（敲键盘时使用预设台词包 / 内置文案）")

    def _on_apply(self) -> None:
        """确认：发 applied 信号（controller 负责写配置与持久化），随后关闭。"""

        pack = self._pack_combo.currentData()
        auto_texts = self.parse_custom_texts(self._auto_edit.toPlainText())
        hit_texts = self.parse_custom_texts(self._hit_edit.toPlainText())
        self.applied.emit(
            str(pack or C.DEFAULT_BUBBLE_TEXT_PACK), auto_texts, hit_texts
        )
        self.accept()
