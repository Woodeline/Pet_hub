"""ui.bubble —— 气泡对话浮层（FR-30 / PRD §4.3 / JP-17）。

独立无边框透明置顶窗口：圆角矩形 + 指向宠物头顶的小三角尖；
出现 0.2s 淡入 → 停留设定时长 → 0.3s 淡出；贴近屏幕顶部时自动翻转到下方。

两种渲染模式：
- 文本模式（情绪气泡）：**完全点击穿透**，不拦截任何鼠标事件。
- 单词模式（日语学习）：四行多字号文本 + 底部「记住了 / 新单词」两个按钮，
  窗口切换为可交互（接收鼠标），超时无操作自动消失（时长由配置注入）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QPushButton, QWidget

from desktop_pet.core import constants as C

if TYPE_CHECKING:  # 仅类型检查期导入，避免 ui 反向依赖 core 的运行时开销
    from desktop_pet.core.vocabulary import VocabEntry

#: 淡入淡出刷新间隔（毫秒）
_FADE_TICK_MS: Final[int] = 16
#: 相位常量
_PHASE_HIDDEN: Final[int] = 0
_PHASE_FADE_IN: Final[int] = 1
_PHASE_HOLD: Final[int] = 2
_PHASE_FADE_OUT: Final[int] = 3
#: 渲染模式（情绪气泡=纯文本；日语学习=四行多字号+按钮）
_MODE_TEXT: Final[int] = 0
_MODE_WORD: Final[int] = 1
#: 窗口旗标：文本模式（完全点击穿透）。运行期切换只用单比特
#: ``WindowTransparentForInput``（见 :meth:`_set_interactive`，本机 PySide6
#: 创建后调用 ``setWindowFlags(组合值)`` 是静默无操作），可交互形态即去掉该位。
_FLAGS_PASSTHRU: Final[Qt.WindowType] = (
    Qt.WindowType.FramelessWindowHint
    | Qt.WindowType.WindowStaysOnTopHint
    | Qt.WindowType.Tool
    | Qt.WindowType.WindowTransparentForInput
)


class BubbleWindow(QWidget):
    """气泡提示窗口（复用单个实例，避免频繁创建/销毁）。"""

    #: 单词模式按钮（仅单词模式可触发；业务判定在 app/controller）
    learned_clicked = Signal()
    new_word_clicked = Signal()

    def __init__(self) -> None:
        """构造气泡窗口。"""

        super().__init__()
        self.setWindowFlags(_FLAGS_PASSTHRU)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._text: str = ""
        self._alpha: float = 0.0
        self._phase: int = _PHASE_HIDDEN
        self._elapsed: float = 0.0
        self._duration: float = C.BUBBLE_MIN_DURATION_S
        self._pointing_down: bool = True  # 默认在宠物上方，三角尖朝下
        self._anchor: QPoint = QPoint(0, 0)

        # 渲染模式与学习泡泡四行内容（默认文本模式，情绪气泡路径不受影响）
        self._mode: int = _MODE_TEXT
        self._line_word: str = ""
        self._line_kana: str = ""
        self._line_translation: str = ""
        self._line_meaning: str = ""

        self._font = QFont("Microsoft YaHei")
        self._font.setPointSize(C.BUBBLE_FONT_SIZE)

        # 学习泡泡四档字号（单词加粗；假名/翻译/释义依次递减）
        self._font_word = QFont(C.JP_BUBBLE_FONT_FAMILY)
        self._font_word.setPointSize(C.JP_BUBBLE_WORD_FONT_SIZE)
        self._font_word.setBold(True)
        self._font_kana = QFont(C.JP_BUBBLE_FONT_FAMILY)
        self._font_kana.setPointSize(C.JP_BUBBLE_KANA_FONT_SIZE)
        self._font_trans = QFont(C.JP_BUBBLE_FONT_FAMILY)
        self._font_trans.setPointSize(C.JP_BUBBLE_TRANSLATION_FONT_SIZE)
        self._font_meaning = QFont(C.JP_BUBBLE_FONT_FAMILY)
        self._font_meaning.setPointSize(C.JP_BUBBLE_MEANING_FONT_SIZE)

        self._timer = QTimer(self)
        self._timer.setInterval(_FADE_TICK_MS)
        self._timer.timeout.connect(self._update_alpha)

        # 单词模式交互按钮（默认隐藏；文本模式下不可见且窗口点击穿透）
        button_style = (
            "QPushButton {"
            " background: #FFFFFF;"
            f" color: {C.COLORS['bubble_text']};"
            f" border: 1.5px solid {C.COLORS['warm_brown']};"
            " border-radius: 6px;"
            f" font-family: '{C.JP_BUBBLE_FONT_FAMILY}';"
            " font-size: 11px;"
            " }"
            "QPushButton:hover { background: #FFF3E0; }"
        )
        self._btn_learned = QPushButton(C.JP_BTN_LEARNED, self)
        self._btn_new = QPushButton(C.JP_BTN_NEW_WORD, self)
        for button in (self._btn_learned, self._btn_new):
            button.setFixedSize(int(C.JP_BUBBLE_BTN_W), int(C.JP_BUBBLE_BTN_H))
            button.setStyleSheet(button_style)
            button.setVisible(False)
        self._btn_learned.clicked.connect(self._on_learned_clicked)
        self._btn_new.clicked.connect(self._on_new_clicked)

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def set_anchor(self, anchor: QPoint) -> None:
        """设置气泡指向的锚点（宠物头顶的**全局**坐标）。"""

        self._anchor = QPoint(anchor)

    def show_message(self, text: str, duration: float) -> None:
        """显示一条气泡消息（文本模式，点击穿透，按钮隐藏）。

        Args:
            text: 显示的文案。
            duration: 停留时长（会被钳制到 ``[2, 4]`` 秒）。
        """

        if not text:
            return
        self._mode = _MODE_TEXT
        self._text = text
        self._duration = min(C.BUBBLE_MAX_DURATION_S, max(C.BUBBLE_MIN_DURATION_S, float(duration)))
        self._elapsed = 0.0
        self._alpha = 0.0
        self._phase = _PHASE_FADE_IN

        self._set_interactive(False)
        self._hide_buttons()
        geometry = self._compute_geometry(self._anchor)
        self.setGeometry(geometry)
        self.setWindowOpacity(0.0)
        self.show()
        self._set_interactive(False)  # 创建后补应用（创建前的切换会被 Qt 丢弃）
        self.setWindowOpacity(0.0)    # 旗标切换会隐式隐藏窗口，重置透明度
        self.show()                   # 重新显示
        self.repaint()                # hide->re-show 后 ULW 位图不刷新，必须同步重绘
        self.raise_()
        self._timer.start()

    def show_word(self, entry: "VocabEntry", duration: float) -> None:
        """显示一条日语单词（四行多字号 + 底部「记住了 / 新单词」按钮）。

        空 ``entry`` 视为 no-op；``duration`` 钳制到
        ``[JP_BUBBLE_DURATION_MIN_S, JP_BUBBLE_DURATION_MAX_S]``（JP-17 可调时长，
        超时无操作自动消失）。学习泡泡**固定内容宽度** = :data:`C.JP_BUBBLE_MAX_WIDTH`，
        保证测量换行宽 == 绘制换行宽。单词模式窗口接收鼠标交互。
        """

        if entry is None or not getattr(entry, "word", ""):
            return
        self._mode = _MODE_WORD
        self._line_word = entry.word
        self._line_kana = entry.kana
        self._line_translation = entry.translation
        self._line_meaning = entry.meaning
        self._duration = min(
            C.JP_BUBBLE_DURATION_MAX_S, max(C.JP_BUBBLE_DURATION_MIN_S, float(duration))
        )
        self._elapsed = 0.0
        self._alpha = 0.0
        self._phase = _PHASE_FADE_IN

        self._set_interactive(True)
        geometry = self._compute_geometry(self._anchor)
        self.setGeometry(geometry)
        self._place_buttons()
        self.setWindowOpacity(0.0)
        self.show()
        self._set_interactive(True)   # 创建后补应用（创建前的切换会被 Qt 丢弃）
        self.setWindowOpacity(0.0)    # 旗标切换会隐式隐藏窗口，重置透明度避免闪帧
        self.show()                   # 重新显示
        self.repaint()                # hide->re-show 后 ULW 位图不刷新，必须同步重绘
        self.raise_()
        self._timer.start()

    def hide_bubble(self) -> None:
        """立即隐藏气泡并复位状态（按钮一并隐藏，恢复点击穿透）。"""

        self._timer.stop()
        self._phase = _PHASE_HIDDEN
        self._alpha = 0.0
        self._hide_buttons()
        self._set_interactive(False)
        self.hide()

    # ------------------------------------------------------------------ #
    # 交互（JP-17）
    # ------------------------------------------------------------------ #
    def _on_learned_clicked(self) -> None:
        """「记住了」：隐藏气泡并通知 controller（业务判定在 app 层）。"""

        self.hide_bubble()
        self.learned_clicked.emit()

    def _on_new_clicked(self) -> None:
        """「新单词」：隐藏气泡并通知 controller（业务判定在 app 层）。"""

        self.hide_bubble()
        self.new_word_clicked.emit()

    def _set_interactive(self, interactive: bool) -> None:
        """在「点击穿透」与「可交互」两种窗口形态间切换。

        ⚠️ 本机 PySide6 的两条实测约束：
        1. 窗口创建后 ``setWindowFlags(组合值)`` 是静默无操作，必须用单比特
           ``setWindowFlag``（原生 ``WS_EX_TRANSPARENT`` 实时更新）。
        2. 窗口创建（首次 ``show``）**之前**对该比特的清除会被 Qt 丢弃，
           因此 :meth:`show_message` / :meth:`show_word` 在 ``show()`` 之后
           还要再调用一次本方法。
        """

        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, not interactive)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, not interactive)

    def _place_buttons(self) -> None:
        """把两个按钮定位到泡泡主体底部居中（仅单词模式可见）。"""

        if self._mode != _MODE_WORD:
            self._hide_buttons()
            return
        bottom = self.height() - (C.BUBBLE_TAIL_H if self._pointing_down else 0.0)
        y = int(round(bottom - C.BUBBLE_PAD_Y - C.JP_BUBBLE_BTN_H))
        total_w = C.JP_BUBBLE_BTN_W * 2.0 + C.JP_BUBBLE_BTN_GAP
        x0 = (self.width() - total_w) / 2.0
        self._btn_learned.move(int(round(x0)), y)
        self._btn_new.move(int(round(x0 + C.JP_BUBBLE_BTN_W + C.JP_BUBBLE_BTN_GAP)), y)
        self._btn_learned.setVisible(True)
        self._btn_new.setVisible(True)

    def _hide_buttons(self) -> None:
        """隐藏两个交互按钮。"""

        self._btn_learned.setVisible(False)
        self._btn_new.setVisible(False)

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """绘制圆角矩形气泡 + 指向三角尖。"""

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setOpacity(max(0.0, min(1.0, self._alpha)))

            tail_h = C.BUBBLE_TAIL_H
            if self._pointing_down:
                body = QRectF(0.0, 0.0, self.width(), self.height() - tail_h)
            else:
                body = QRectF(0.0, tail_h, self.width(), self.height() - tail_h)

            bg = QColor(C.COLORS["bubble_bg"])
            border = QColor(C.COLORS["warm_brown"])

            path = QPainterPath()
            path.addRoundedRect(body, C.BUBBLE_CORNER_RADIUS, C.BUBBLE_CORNER_RADIUS)

            # 三角尖
            cx = self.width() / 2.0
            half = C.BUBBLE_TAIL_W / 2.0
            tail = QPainterPath()
            if self._pointing_down:
                tail.moveTo(cx - half, body.bottom() - 0.5)
                tail.lineTo(cx, body.bottom() + tail_h)
                tail.lineTo(cx + half, body.bottom() - 0.5)
            else:
                tail.moveTo(cx - half, body.top() + 0.5)
                tail.lineTo(cx, body.top() - tail_h)
                tail.lineTo(cx + half, body.top() + 0.5)
            tail.closeSubpath()
            path = path.united(tail)

            painter.setPen(QPen(border, 1.8))
            painter.setBrush(bg)
            painter.drawPath(path)

            # 文字
            if self._mode == _MODE_WORD:
                self._paint_word(painter, body)
            else:
                painter.setPen(QPen(QColor(C.COLORS["bubble_text"])))
                painter.setFont(self._font)
                text_rect = body.adjusted(
                    C.BUBBLE_PAD_X, C.BUBBLE_PAD_Y, -C.BUBBLE_PAD_X, -C.BUBBLE_PAD_Y
                )
                painter.drawText(
                    text_rect,
                    int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
                    self._text,
                )
        finally:
            painter.end()

    def _paint_word(self, painter: QPainter, body: QRectF) -> None:
        """绘制学习泡泡四行文本块（各行独立字号/颜色，水平居中、整块垂直居中）。"""

        wrap_w = C.JP_BUBBLE_MAX_WIDTH
        layout = self._word_layout(wrap_w)
        if not layout:
            return

        # 文本块垂直区域需为底部按钮行让位（按钮高 + 行间距）
        content = body.adjusted(
            C.BUBBLE_PAD_X,
            C.BUBBLE_PAD_Y,
            -C.BUBBLE_PAD_X,
            -(C.BUBBLE_PAD_Y + C.JP_BUBBLE_BTN_H + C.JP_BUBBLE_BTN_ROW_SPACING),
        )
        spacing = C.BUBBLE_LINE_SPACING
        total_h = sum(rect.height() for _f, _c, _t, rect in layout) + spacing * (len(layout) - 1)
        left = content.left() + max(0.0, (content.width() - wrap_w) / 2.0)
        y = content.top() + max(0.0, (content.height() - total_h) / 2.0)

        for font, color, text, rect in layout:
            painter.setFont(font)
            painter.setPen(QPen(QColor(color)))
            row_h = rect.height()
            painter.drawText(
                QRectF(left, y, wrap_w, row_h),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
                text,
            )
            y += row_h + spacing

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _update_alpha(self) -> None:
        """按相位推进透明度（淡入 / 停留 / 淡出）。"""

        self._elapsed += _FADE_TICK_MS / 1000.0

        if self._phase == _PHASE_FADE_IN:
            self._alpha = min(1.0, self._elapsed / C.BUBBLE_FADE_IN_S)
            if self._elapsed >= C.BUBBLE_FADE_IN_S:
                self._phase = _PHASE_HOLD
                self._alpha = 1.0
        elif self._phase == _PHASE_HOLD:
            if self._elapsed >= C.BUBBLE_FADE_IN_S + self._duration:
                self._phase = _PHASE_FADE_OUT
        elif self._phase == _PHASE_FADE_OUT:
            fade_start = C.BUBBLE_FADE_IN_S + self._duration
            self._alpha = 1.0 - (self._elapsed - fade_start) / C.BUBBLE_FADE_OUT_S
            if self._alpha <= 0.0:
                self.hide_bubble()
                return

        self.setWindowOpacity(max(0.0, min(1.0, self._alpha)))
        self.update()

    def _measure(self, text: str) -> QRectF:
        """测量文字在最大宽度约束下的包围盒。"""

        metrics = QFontMetricsF(self._font)
        return metrics.boundingRect(
            QRectF(0.0, 0.0, C.BUBBLE_MAX_WIDTH, 10000.0),
            int(Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap),
            text,
        )

    def _word_layout(self, wrap_w: float) -> list[tuple[QFont, str, str, QRectF]]:
        """构造学习泡泡四行的 (字体, 颜色, 文本, 测量盒) 布局。

        以 **同一换行宽度** ``wrap_w`` 测量，测量与绘制的换行结果必然一致。
        空行（如缺失字段）被跳过。
        """

        rows = (
            (self._font_word, C.COLORS["bubble_text"], self._line_word),
            (self._font_kana, C.COLORS["bubble_sub_text"], self._line_kana),
            (self._font_trans, C.COLORS["bubble_text"], self._line_translation),
            (self._font_meaning, C.COLORS["bubble_faint_text"], self._line_meaning),
        )
        layout: list[tuple[QFont, str, str, QRectF]] = []
        for font, color, text in rows:
            if not text:
                continue
            metrics = QFontMetricsF(font)
            rect = metrics.boundingRect(
                QRectF(0.0, 0.0, wrap_w, 10000.0),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
                text,
            )
            # 单行时以行高兜底，避免紧包围盒裁掉上下缘
            rect.setHeight(max(rect.height(), metrics.height()))
            layout.append((font, color, text, rect))
        return layout

    def _measure_word(self) -> QRectF:
        """测量学习泡泡四行文本块的包围盒（宽 ≤ ``JP_BUBBLE_MAX_WIDTH``）。"""

        layout = self._word_layout(C.JP_BUBBLE_MAX_WIDTH)
        if not layout:
            return QRectF(0.0, 0.0, 0.0, 0.0)
        spacing = C.BUBBLE_LINE_SPACING
        width = max(rect.width() for _f, _c, _t, rect in layout)
        height = sum(rect.height() for _f, _c, _t, rect in layout) + spacing * (len(layout) - 1)
        return QRectF(0.0, 0.0, width, height)

    def _compute_geometry(self, anchor: QPoint) -> QRect:
        """根据锚点计算气泡窗口几何（贴近屏幕顶部时翻转）。

        Args:
            anchor: 宠物头顶的全局坐标。

        Returns:
            气泡窗口的全局 :class:`QRect`。
        """

        if self._mode == _MODE_WORD:
            measured = self._measure_word()
            content_w = C.JP_BUBBLE_MAX_WIDTH + C.BUBBLE_PAD_X * 2.0
            # 单词模式额外加底部按钮行高度（按钮 + 与文本块间距）
            extra_h = C.JP_BUBBLE_BTN_H + C.JP_BUBBLE_BTN_ROW_SPACING
        else:
            measured = self._measure(self._text)
            content_w = min(C.BUBBLE_MAX_WIDTH, max(40.0, measured.width())) + C.BUBBLE_PAD_X * 2.0
            extra_h = 0.0
        content_h = max(20.0, measured.height()) + C.BUBBLE_PAD_Y * 2.0 + extra_h
        w = int(round(content_w))
        h = int(round(content_h)) + int(round(C.BUBBLE_TAIL_H))

        x = int(round(anchor.x() - w / 2.0))
        y_above = int(round(anchor.y() - C.BUBBLE_GAP_TO_PET - h))

        # 屏幕边界处理（贴近顶部翻转 + 水平钳制）
        screen = QGuiApplication.screenAt(anchor)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            if y_above < avail.top():
                self._pointing_down = False
                y = int(round(anchor.y() + C.BUBBLE_GAP_TO_PET))
                # 若下方也越界，则夹回屏内
                if y + h > avail.bottom():
                    y = max(avail.top(), avail.bottom() - h)
            else:
                self._pointing_down = True
                y = y_above
            x = max(avail.left(), min(x, avail.right() - w))
        else:
            self._pointing_down = True
            y = y_above

        return QRect(x, y, w, h)


__all__ = ["BubbleWindow"]
