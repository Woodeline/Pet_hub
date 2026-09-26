"""ui.bubble_text_dialog —— 情绪气泡台词设置对话框（预设台词包 + 自定义台词）。

职责边界（对齐 ui 层其它业务窗口）：

- 只做「选择与编辑」的 UI，业务判定在 ``app.controller``：确定时经
  :attr:`applied` 信号交回 ``(pack, custom_texts)``，由 controller 写配置并持久化；
- **不触碰单词泡泡**：本对话框只影响 ``controller._show_bubble_for`` 的台词来源，
  ``BubbleWindow.show_word`` 及日语学习模块零关联；
- 生效无需重启：controller 每次弹情绪气泡都现读 ``cfg``，对话框确认即生效。

编辑约定：自定义台词区**一行一条**；非空行 strip、去空、去重、限长
（上限见 ``C.BUBBLE_TEXT_CUSTOM_MAX_*``，真正的清洗在
``core.config._coerce_bubble_texts_custom``，此处预览计数做同样规则）。
自定义池**非空即优先于预设包**；清空编辑区 = 回落预设包。
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

        dlg = BubbleTextDialog(cfg.bubble_text_pack, cfg.bubble_texts_custom)
        dlg.applied.connect(self._on_bubble_text_applied)
        dlg.show()
    """

    #: 确认应用：(预设包名, 自定义台词列表)——清洗后的最终值
    applied = Signal(str, list)

    def __init__(
        self,
        pack: str = C.DEFAULT_BUBBLE_TEXT_PACK,
        custom_texts: list[str] | None = None,
        parent=None,
    ) -> None:
        """构造对话框并回填当前配置。

        Args:
            pack: 当前预设台词包名。
            custom_texts: 当前自定义台词列表（空 = 未启用）。
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

        self._custom_edit = QPlainTextEdit()
        self._custom_edit.setPlaceholderText(
            "自定义台词：一行一条（留空 = 使用上方预设台词包）\n"
            f"最多 {C.BUBBLE_TEXT_CUSTOM_MAX_COUNT} 条，每条最长 "
            f"{C.BUBBLE_TEXT_CUSTOM_MAX_LEN} 字；自定义非空时优先于预设包。\n"
            "示例：\n摸摸我呀~\n加油鸭！"
        )
        self._custom_edit.setPlainText("\n".join(custom_texts or []))
        self._custom_edit.textChanged.connect(self._update_count)

        self._count_label = QLabel()
        self._update_count()

        apply_btn = QPushButton("应用")
        cancel_btn = QPushButton("取消")
        apply_btn.setDefault(True)
        apply_btn.clicked.connect(self._on_apply)
        cancel_btn.clicked.connect(self.reject)

        pack_box = QGroupBox("预设台词包")
        pack_layout = QVBoxLayout(pack_box)
        pack_layout.addWidget(QLabel("选择一套内置风格（自定义池非空时会被跳过）："))
        pack_layout.addWidget(self._pack_combo)

        custom_box = QGroupBox("自定义台词")
        custom_layout = QVBoxLayout(custom_box)
        custom_layout.addWidget(self._custom_edit)
        custom_layout.addWidget(self._count_label)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(cancel_btn)
        buttons.addWidget(apply_btn)

        root = QVBoxLayout(self)
        root.addWidget(pack_box)
        root.addWidget(custom_box)
        root.addLayout(buttons)

        self.resize(420, 360)

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def load_state(self, pack: str, custom_texts: list[str]) -> None:
        """按当前配置回填 UI（重开对话框时由 controller 调用，拿到最新值）。"""

        self._pack_combo.setCurrentText(self._pack_label(str(pack or "default")))
        self._custom_edit.setPlainText("\n".join(custom_texts or []))
        self._update_count()

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
        """把编辑区文本解析为清洗后的台词列表（一行一条，规则与 config coerce 一致）。"""

        cleaned: list[str] = []
        for line in raw.splitlines():
            text = line.strip()
            if not text or text in cleaned:
                continue
            cleaned.append(text[: C.BUBBLE_TEXT_CUSTOM_MAX_LEN])
            if len(cleaned) >= C.BUBBLE_TEXT_CUSTOM_MAX_COUNT:
                break
        return cleaned

    def _update_count(self) -> None:
        """实时刷新自定义台词计数（与 config 清洗规则一致）。"""

        count = len(self.parse_custom_texts(self._custom_edit.toPlainText()))
        if count:
            self._count_label.setText(
                f"已启用自定义：{count} 条（优先于预设台词包）"
            )
        else:
            self._count_label.setText("未启用自定义（使用上方预设台词包）")

    def _on_apply(self) -> None:
        """确认：发 applied 信号（controller 负责写配置与持久化），随后关闭。"""

        pack = self._pack_combo.currentData()
        texts = self.parse_custom_texts(self._custom_edit.toPlainText())
        self.applied.emit(str(pack or C.DEFAULT_BUBBLE_TEXT_PACK), texts)
        self.accept()
