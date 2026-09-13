"""ui.bubble —— 气泡对话浮层（FR-30 / PRD §4.3）。

独立无边框透明置顶窗口：圆角矩形 + 指向宠物头顶的小三角尖；
出现 0.2s 淡入 → 停留 2~4s → 0.3s 淡出；贴近屏幕顶部时自动翻转到下方。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtWidgets import QWidget

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
#: 渲染模式（情绪气泡=纯文本；日语学习=四行多字号）
_MODE_TEXT: Final[int] = 0
_MODE_WORD: Final[int] = 1


class BubbleWindow(QWidget):
    """气泡提示窗口（复用单个实例，避免频繁创建/销毁）。"""

    def __init__(self) -> None:
        """构造气泡窗口。"""

        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowTransparentForInput
        )
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

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def set_anchor(self, anchor: QPoint) -> None:
        """设置气泡指向的锚点（宠物头顶的**全局**坐标）。"""

        self._anchor = QPoint(anchor)

    def show_message(self, text: str, duration: float) -> None:
        """显示一条气泡消息。

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

        geometry = self._compute_geometry(self._anchor)
        self.setGeometry(geometry)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._timer.start()

    def show_word(self, entry: "VocabEntry", duration: float) -> None:
        """显示一条日语单词（四行多字号：单词 / 假名 / 翻译 / 释义）。

        空 ``entry`` 视为 no-op；``duration`` 同 :meth:`show_message` 钳制到 ``[2, 4]`` 秒。
        学习泡泡**固定内容宽度** = :data:`C.JP_BUBBLE_MAX_WIDTH`，保证测量换行宽 == 绘制换行宽。
        """

        if entry is None or not getattr(entry, "word", ""):
            return
        self._mode = _MODE_WORD
        self._line_word = entry.word
        self._line_kana = entry.kana
        self._line_translation = entry.translation
        self._line_meaning = entry.meaning
        self._duration = min(C.BUBBLE_MAX_DURATION_S, max(C.BUBBLE_MIN_DURATION_S, float(duration)))
        self._elapsed = 0.0
        self._alpha = 0.0
        self._phase = _PHASE_FADE_IN

        geometry = self._compute_geometry(self._anchor)
        self.setGeometry(geometry)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._timer.start()

    def hide_bubble(self) -> None:
        """立即隐藏气泡并复位状态。"""

        self._timer.stop()
        self._phase = _PHASE_HIDDEN
        self._alpha = 0.0
        self.hide()

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

        content = body.adjusted(C.BUBBLE_PAD_X, C.BUBBLE_PAD_Y, -C.BUBBLE_PAD_X, -C.BUBBLE_PAD_Y)
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
        else:
            measured = self._measure(self._text)
            content_w = min(C.BUBBLE_MAX_WIDTH, max(40.0, measured.width())) + C.BUBBLE_PAD_X * 2.0
        content_h = max(20.0, measured.height()) + C.BUBBLE_PAD_Y * 2.0
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
