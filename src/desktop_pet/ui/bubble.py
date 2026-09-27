"""ui.bubble —— 气泡对话浮层（FR-30 / PRD §4.3）。

独立无边框透明置顶窗口：圆角矩形 + 指向宠物头顶的小三角尖；
出现 0.2s 淡入 → 停留 2~4s → 0.3s 淡出；贴近屏幕顶部时自动翻转到下方。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QPoint, QPointF, QRect, QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QLinearGradient,
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
        self._line_level: str = ""  # 学习泡泡右上角等级 chip（N5..N1）

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

        # 打字感（阶段 B2-3）：reveal 进度 0→1，仅作用于学习泡泡「单词」行（``layout[0]``）。
        # 尺寸测量仍按**完整词条**一次算定（``_measure_word`` / ``_word_layout``），
        # 打字过程中气泡宽度恒定（``test_jp_bubble_visual`` 固定宽度契约不破）。
        self._reveal: float = 1.0
        self._reduce_motion: bool = False
        self._reveal_timer = QTimer(self)
        self._reveal_timer.setInterval(int(C.BUBBLE_TYPE_TICK_MS))
        self._reveal_timer.timeout.connect(self._advance_reveal)

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def set_anchor(self, anchor: QPoint) -> None:
        """设置气泡指向的锚点（宠物头顶的**全局**坐标）。"""

        self._anchor = QPoint(anchor)

    def pointing_down(self) -> bool:
        """返回当前三角尖是否朝下（供按钮条几何对齐；``True`` = 气泡在宠物上方）。"""

        return self._pointing_down

    def set_reduce_motion(self, active: bool) -> None:
        """设置「减少动效」开关（阶段 B2-3）。

        开启时气泡**跳过逐字打字**、直接全显（``reveal = 1.0``），对动效敏感者更友好。
        """

        self._reduce_motion = bool(active)

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
        # 情绪气泡为纯文本模式，非打字感目标 → 直接全显、停止逐字定时器
        self._reveal = 1.0
        self._reveal_timer.stop()

        geometry = self._compute_geometry(self._anchor)
        self.setGeometry(geometry)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._timer.start()

    def show_word(self, entry: "VocabEntry", duration: float) -> None:
        """显示一条日语单词（四行多字号：单词 / 假名 / 翻译 / 释义）。

        空 ``entry`` 视为 no-op；``duration`` 钳制到学习泡泡范围 ``[JP_BUBBLE_MIN, JP_BUBBLE_MAX]``
        秒（默认 30s，与情绪泡泡 ``[2,4]s`` 解耦，见设计 §1.4 难点 4）。
        学习泡泡**固定内容宽度** = :data:`C.JP_BUBBLE_MAX_WIDTH`，保证测量换行宽 == 绘制换行宽。
        """

        if entry is None or not getattr(entry, "word", ""):
            return
        self._mode = _MODE_WORD
        self._line_word = entry.word
        self._line_kana = entry.kana
        self._line_translation = entry.translation
        self._line_meaning = entry.meaning
        self._line_level = entry.level
        self._duration = min(
            C.JP_BUBBLE_MAX_DURATION_S, max(C.JP_BUBBLE_MIN_DURATION_S, float(duration))
        )
        self._elapsed = 0.0
        self._alpha = 0.0
        self._phase = _PHASE_FADE_IN
        # 打字感：非 reduce_motion 时从 0 起逐字显示单词；reduce_motion 直接全显
        self._reveal = 1.0 if self._reduce_motion else 0.0
        self._reveal_timer.stop()
        if not self._reduce_motion and self._line_word:
            self._reveal_timer.start()

        geometry = self._compute_geometry(self._anchor)
        self.setGeometry(geometry)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._timer.start()

    def hide_bubble(self) -> None:
        """立即隐藏气泡并复位状态。"""

        self._timer.stop()
        self._reveal_timer.stop()
        self._reveal = 1.0
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
            m = C.BUBBLE_STROKE_MARGIN
            if self._pointing_down:
                body = QRectF(
                    m, m, self.width() - 2.0 * m, self.height() - tail_h - 2.0 * m
                )
            else:
                body = QRectF(
                    m, m + tail_h, self.width() - 2.0 * m, self.height() - tail_h - 2.0 * m
                )

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

            # 底部柔和阴影（多层半透明圆角矩形错位，画在 body 之前）
            self._paint_shadow(painter, body)

            # body 三段垂直渐变：顶高光 → 奶白 → 底部略深
            body_fill = QLinearGradient(body.topLeft(), body.bottomLeft())
            body_fill.setColorAt(0.0, QColor(C.COLORS["bubble_gradient_hi"]))
            body_fill.setColorAt(0.5, QColor(C.COLORS["bubble_bg"]))
            body_fill.setColorAt(1.0, QColor(C.COLORS["bubble_gradient_bottom"]))

            # 双层描边（细线贴纸风）：先画宽白晕（外露约 1.2px 白环，深色壁纸靠它
            # 分离、托出「浮起」的气泡感），再画 1px 淡灰细线轻勾轮廓。同一
            # united path，body+尾巴一次成形。
            halo = QColor(C.COLORS["bubble_halo"])
            halo.setAlpha(C.BUBBLE_HALO_ALPHA)
            painter.setBrush(body_fill)
            painter.setPen(QPen(halo, C.BUBBLE_HALO_WIDTH))
            painter.drawPath(path)
            painter.setPen(QPen(QColor(C.COLORS["bubble_border"]), C.BUBBLE_BORDER_WIDTH))
            painter.drawPath(path)

            # 文字
            if self._mode == _MODE_WORD:
                self._paint_highlight(painter, body)
                self._paint_divider(painter, body)
                self._paint_word(painter, body)
                self._paint_level_chip(painter, body)
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

    def _paint_highlight(self, painter: QPainter, body: QRectF) -> None:
        """在学习泡泡 body 顶部叠加一层 ``bubble_gradient_hi`` 浅高光（质感，设计 §7.3）。"""

        base = QColor(C.COLORS["bubble_gradient_hi"])
        gradient = QLinearGradient(body.topLeft(), body.bottomLeft())
        gradient.setColorAt(0.0, QColor(base.red(), base.green(), base.blue(), 90))
        gradient.setColorAt(0.35, QColor(base.red(), base.green(), base.blue(), 0))
        highlight = QRectF(
            body.left() + 2.0,
            body.top() + 2.0,
            body.width() - 4.0,
            body.height() * 0.5,
        )
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawRoundedRect(
            highlight,
            max(0.0, C.BUBBLE_CORNER_RADIUS - 2.0),
            max(0.0, C.BUBBLE_CORNER_RADIUS - 2.0),
        )
        painter.restore()

    def _paint_shadow(self, painter: QPainter, body: QRectF) -> None:
        """在 body 下方绘制多层半透明圆角矩形错位阴影（底部柔和阴影，设计 §A1.1）。"""

        base = QColor(C.COLORS["bubble_shadow"])
        # (向下偏移量, 透明度) —— 越远越淡，形成柔和渐变阴影。
        # 比旧版（20/14/9）更深：STROKE_MARGIN 让出了绘制空间，且白晕需要
        # 阴影配合才能在浅色壁纸上提供下缘分离。
        layers: tuple[tuple[float, int], ...] = ((4.0, 34), (2.5, 24), (1.0, 16))
        painter.save()
        painter.setPen(Qt.PenStyle.NoPen)
        for offset, alpha in layers:
            shadow_rect = QRectF(
                body.left(), body.top() + offset, body.width(), body.height()
            )
            painter.setBrush(QColor(base.red(), base.green(), base.blue(), alpha))
            painter.drawRoundedRect(
                shadow_rect, C.BUBBLE_CORNER_RADIUS, C.BUBBLE_CORNER_RADIUS
            )
        painter.restore()

    def _paint_divider(self, painter: QPainter, body: QRectF) -> None:
        """在「单词/假名」与「翻译/释义」之间绘制一条浅色分割线。"""

        wrap_w = C.JP_BUBBLE_MAX_WIDTH
        layout = self._word_layout(wrap_w)
        if len(layout) < 3:
            return
        content = body.adjusted(
            C.BUBBLE_PAD_X, C.BUBBLE_PAD_Y, -C.BUBBLE_PAD_X, -C.BUBBLE_PAD_Y
        )
        spacing = C.BUBBLE_LINE_SPACING
        total_h = sum(rect.height() for _f, _c, _t, rect in layout) + spacing * (len(layout) - 1)
        left = content.left() + max(0.0, (content.width() - wrap_w) / 2.0)
        y = content.top() + max(0.0, (content.height() - total_h) / 2.0)
        # 前两行（单词 + 假名）结束后，再往下偏移半行距即分割线
        y += layout[0][3].height() + spacing + layout[1][3].height() + spacing / 2.0

        painter.save()
        painter.setPen(QPen(QColor(C.COLORS["bubble_divider"]), 1.0))
        painter.drawLine(QPointF(left + 4.0, y), QPointF(left + wrap_w - 4.0, y))
        painter.restore()

    def _paint_level_chip(self, painter: QPainter, body: QRectF) -> None:
        """在 body 右上角绘制等级 chip（N5..N1）。"""

        level = self._line_level
        if not level:
            return
        font = QFont(C.JP_BUBBLE_FONT_FAMILY)
        font.setPointSize(9)
        font.setBold(True)
        painter.save()
        painter.setFont(font)
        metrics = QFontMetricsF(font)
        text_w = metrics.horizontalAdvance(level)
        chip_w = text_w + 12.0
        chip_h = 18.0
        chip_rect = QRectF(
            body.right() - chip_w - 6.0, body.top() + 6.0, chip_w, chip_h
        )
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(C.COLORS["jp_level_chip_bg"]))
        painter.drawRoundedRect(chip_rect, 8.0, 8.0)
        painter.setPen(QPen(QColor(C.COLORS["jp_level_chip_text"])))
        painter.drawText(chip_rect, int(Qt.AlignmentFlag.AlignCenter), level)
        painter.restore()

    def _paint_word(self, painter: QPainter, body: QRectF) -> None:
        """绘制学习泡泡四行文本块（各行独立字号/颜色，水平居中、整块垂直居中）。

        **打字感（阶段 B2-3）**：``layout[0]`` 恒为「单词」行（``_word_layout`` 的行序
        首项，且 ``show_word`` 要求 ``entry.word`` 非空），按 ``self._reveal`` 绘制其
        **前缀子串**；其余行（假名 / 翻译 / 释义）全显。测量仍按完整文本一次算定，
        故打字期间气泡尺寸恒定。
        """

        wrap_w = C.JP_BUBBLE_MAX_WIDTH
        layout = self._word_layout(wrap_w)
        if not layout:
            return

        content = body.adjusted(C.BUBBLE_PAD_X, C.BUBBLE_PAD_Y, -C.BUBBLE_PAD_X, -C.BUBBLE_PAD_Y)
        spacing = C.BUBBLE_LINE_SPACING
        total_h = sum(rect.height() for _f, _c, _t, rect in layout) + spacing * (len(layout) - 1)
        left = content.left() + max(0.0, (content.width() - wrap_w) / 2.0)
        y = content.top() + max(0.0, (content.height() - total_h) / 2.0)

        for index, (font, color, text, rect) in enumerate(layout):
            painter.setFont(font)
            painter.setPen(QPen(QColor(color)))
            row_h = rect.height()
            draw_text = self._revealed_text(text) if index == 0 else text
            painter.drawText(
                QRectF(left, y, wrap_w, row_h),
                int(Qt.AlignmentFlag.AlignHCenter | Qt.TextFlag.TextWordWrap),
                draw_text,
            )
            y += row_h + spacing

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _revealed_text(self, text: str) -> str:
        """按当前 reveal 进度返回 ``text`` 的**前缀子串**（阶段 B2-3 打字感）。

        * ``reveal >= 1`` 或空文本 → 原样返回（全显）；
        * ``reveal <= 0`` → 空串（一个字都还没"打"出来）；
        * 其间 → ``text[:max(1, int(reveal * len(text)))]``（至少先显 1 个字）。
        """

        if self._reveal >= 1.0 or not text:
            return text
        if self._reveal <= 0.0:
            return ""
        return text[: max(1, int(self._reveal * len(text)))]

    def _advance_reveal(self) -> None:
        """按固定速率推进打字感 reveal 进度；到 1.0 后**停止**逐字定时器（阶段 B2-3）。

        速率 = 单字符时长 ``BUBBLE_TYPE_CHAR_S``，故一个词的打字总时长 = 字数 × 该值，
        与 ``BUBBLE_TYPE_TICK_MS`` 无关（定时器间隔只决定刷新粒度）。
        """

        chars = len(self._line_word)
        if chars <= 0 or C.BUBBLE_TYPE_CHAR_S <= 0.0:
            self._reveal = 1.0
            self._reveal_timer.stop()
            return
        step = (C.BUBBLE_TYPE_TICK_MS / 1000.0) / (chars * C.BUBBLE_TYPE_CHAR_S)
        self._reveal = min(1.0, self._reveal + step)
        if self._reveal >= 1.0:
            self._reveal_timer.stop()
        self.update()

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
        # 窗口 = 内容 + 双侧描边预留（STROKE_MARGIN，防止描边被窗口边缘裁掉一半）+ 尾巴
        m2 = C.BUBBLE_STROKE_MARGIN * 2.0
        w = int(round(content_w)) + int(round(m2))
        h = int(round(content_h)) + int(round(C.BUBBLE_TAIL_H)) + int(round(m2))

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
