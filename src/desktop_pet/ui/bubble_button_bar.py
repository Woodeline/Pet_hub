"""ui.bubble_button_bar —— 学习泡泡下方的常驻可交互按钮条浮层（JP-17+）。

独立无边框透明置顶窗口：两个圆角胶囊按钮（「记住了」主色填充 /「新单词」描边）。
与 :class:`~desktop_pet.ui.bubble.BubbleWindow` 用**相同**的淡入 / 停留 / 淡出相位常量
与 16ms tick，视觉同步（设计 §3.1 / §1.4 难点 2）。

**常驻可交互**：从构造起**不设** ``WindowTransparentForInput``、**不设**
``WA_TransparentForMouseEvents``（规避 Windows 平台「单比特切换穿透标志」的坑），
文字区气泡保持透传，二者永不运行时切换穿透标志。
"""

from __future__ import annotations

from typing import Final

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QPen
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHBoxLayout, QPushButton, QWidget

from desktop_pet.core import constants as C

#: 淡入淡出刷新间隔（毫秒，与 bubble 一致）
_FADE_TICK_MS: Final[int] = 16
#: 相位常量（与 bubble 一致）
_PHASE_HIDDEN: Final[int] = 0
_PHASE_FADE_IN: Final[int] = 1
_PHASE_HOLD: Final[int] = 2
_PHASE_FADE_OUT: Final[int] = 3
#: 两按钮间距（逻辑像素）
_BUTTON_SPACING: Final[int] = 8


class BubbleButtonBar(QWidget):
    """学习单词按钮条（常驻可交互浮层，复用单实例）。

    双模式（几何 / 样式完全复用，仅换文案与信号路由）：
    - 学习模式（默认）：「记住了」（主色）/「新单词」（描边）→ ``mastered_clicked`` / ``vocab_clicked``；
    - 复习模式（``show_bar(review=True)``，记忆曲线）：「还记得」/「忘了」
      → ``review_ok_clicked`` / ``review_lapsed_clicked``。
    """

    mastered_clicked = Signal()
    vocab_clicked = Signal()
    review_ok_clicked = Signal()
    review_lapsed_clicked = Signal()

    def __init__(self) -> None:
        """构造按钮条窗口。"""

        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        # 刻意不设 WindowTransparentForInput / WA_TransparentForMouseEvents

        self._btn_mastered = QPushButton(C.JP_BUTTON_MASTERED, self)
        self._btn_vocab = QPushButton(C.JP_BUTTON_VOCAB, self)
        for btn in (self._btn_mastered, self._btn_vocab):
            btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._btn_mastered.setObjectName("masteredButton")
        self._btn_vocab.setObjectName("vocabButton")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            C.JP_BUTTON_BAR_PAD, C.JP_BUTTON_BAR_PAD, C.JP_BUTTON_BAR_PAD, C.JP_BUTTON_BAR_PAD
        )
        layout.setSpacing(_BUTTON_SPACING)
        layout.addWidget(self._btn_mastered)
        layout.addWidget(self._btn_vocab)

        self._btn_mastered.clicked.connect(self._emit_primary)
        self._btn_vocab.clicked.connect(self._emit_secondary)

        # 复习模式标志：True 时主按钮 = 「还记得」(review_ok)、副按钮 = 「忘了」(review_lapsed)
        self._review_mode: bool = False

        self.setStyleSheet(self._build_qss())

        # 轻投影：主按钮底部柔和阴影（微交互质感，设计 §A1.1）
        shadow_color = QColor(C.COLORS["bubble_shadow"])
        shadow_color.setAlpha(70)
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(10)
        shadow.setOffset(0, 2)
        shadow.setColor(shadow_color)
        self._btn_mastered.setGraphicsEffect(shadow)

        # 相位机（与气泡一致的淡入/停留/淡出）
        self._phase: int = _PHASE_HIDDEN
        self._elapsed: float = 0.0
        self._alpha: float = 0.0
        self._duration: float = C.JP_BUBBLE_DURATION_S

        self._timer = QTimer(self)
        self._timer.setInterval(_FADE_TICK_MS)
        self._timer.timeout.connect(self._update_alpha)

        # 让 sizeHint 计算到真实尺寸，供几何计算使用
        self.adjustSize()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def show_bar(
        self,
        anchor: QPoint,
        bubble_rect: QRect,
        pointing_down: bool,
        duration: float,
        review: bool = False,
    ) -> None:
        """在气泡尾尖下方（或上方）显示按钮条并启动相位机。

        Args:
            anchor: 气泡指向的锚点（宠物头顶全局坐标）。
            bubble_rect: 气泡窗口的全局 :class:`QRect`。
            pointing_down: 气泡三角尖是否朝下（决定按钮条在气泡下方还是上方）。
            duration: 停留时长（秒，钳制到学习泡泡时长范围）。
            review: ``True`` = 复习模式（「还记得 / 忘了」，记忆曲线作答按钮）。
        """

        self._set_review_mode(review)
        self._duration = min(
            C.JP_BUBBLE_MAX_DURATION_S, max(C.JP_BUBBLE_MIN_DURATION_S, float(duration))
        )
        self._elapsed = 0.0
        self._alpha = 0.0
        self._phase = _PHASE_FADE_IN

        geometry = self._compute_geometry(anchor, bubble_rect, pointing_down)
        self.setGeometry(geometry)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self._timer.start()

    def hide_bar(self) -> None:
        """立即隐藏按钮条并复位状态（controller 在 dispose 时调用）。"""

        self._timer.stop()
        self._phase = _PHASE_HIDDEN
        self._alpha = 0.0
        self._review_mode = False
        self.hide()

    # ------------------------------------------------------------------ #
    # 模式与信号路由
    # ------------------------------------------------------------------ #
    def _set_review_mode(self, review: bool) -> None:
        """切换学习 / 复习模式文案（信号路由在点击时按标志分发）。"""

        self._review_mode = bool(review)
        if self._review_mode:
            self._btn_mastered.setText(C.JP_BUTTON_REVIEW_OK)
            self._btn_vocab.setText(C.JP_BUTTON_REVIEW_LAPSED)
        else:
            self._btn_mastered.setText(C.JP_BUTTON_MASTERED)
            self._btn_vocab.setText(C.JP_BUTTON_VOCAB)

    def _emit_primary(self) -> None:
        """主按钮点击 → 按当前模式分发（复习 = 还记得；学习 = 记住了）。"""

        if self._review_mode:
            self.review_ok_clicked.emit()
        else:
            self.mastered_clicked.emit()

    def _emit_secondary(self) -> None:
        """副按钮点击 → 按当前模式分发（复习 = 忘了；学习 = 新单词）。"""

        if self._review_mode:
            self.review_lapsed_clicked.emit()
        else:
            self.vocab_clicked.emit()

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #
    def paintEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """绘制按钮条圆角底色（按钮自身由 QSS 绘制）。"""

        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setOpacity(max(0.0, min(1.0, self._alpha)))
            rect = QRectF(0.5, 0.5, self.width() - 1.0, self.height() - 1.0)
            painter.setPen(QPen(QColor(C.COLORS["jp_button_secondary_border"]), 1.0))
            painter.setBrush(QColor(C.COLORS["jp_button_bar_bg"]))
            painter.drawRoundedRect(rect, C.JP_BUTTON_RADIUS, C.JP_BUTTON_RADIUS)
        finally:
            painter.end()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _build_qss(self) -> str:
        """构造两按钮的胶囊 QSS（渐变填充 + 悬停 / 按下反馈，色值取自 ``C.COLORS``/``C.JP_BUTTON_*``）。"""

        radius = C.JP_BUTTON_RADIUS
        pad_x = C.JP_BUTTON_PAD_X
        pad_y = C.JP_BUTTON_PAD_Y
        font_size = C.JP_BUTTON_FONT_SIZE
        font_family = C.JP_BUBBLE_FONT_FAMILY

        primary_top = C.COLORS["jp_button_primary_hover"]
        primary_mid = C.COLORS["jp_button_primary_bg"]
        primary_bottom = C.COLORS["jp_button_primary_pressed"]

        mastered_normal = (
            "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {primary_top}, stop:0.5 {primary_mid}, stop:1 {primary_bottom})"
        )
        mastered_hover = (
            "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {primary_top}, stop:1 {primary_mid})"
        )
        mastered_pressed = (
            "qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {primary_mid}, stop:1 {primary_bottom})"
        )

        return (
            f"#masteredButton {{"
            f"background: {mastered_normal};"
            f"color: {C.COLORS['jp_button_primary_text']};"
            f"border: none; border-radius: {radius}px;"
            f"padding: {pad_y}px {pad_x}px;"
            f"font-size: {font_size}px; font-family: \"{font_family}\";"
            f"}}"
            f"#masteredButton:hover {{ background: {mastered_hover}; }}"
            f"#masteredButton:pressed {{ background: {mastered_pressed}; }}"
            f"#vocabButton {{"
            f"background-color: transparent;"
            f"color: {C.COLORS['jp_button_secondary_text']};"
            f"border: 1px solid {C.COLORS['jp_button_secondary_border']};"
            f"border-radius: {radius}px;"
            f"padding: {pad_y}px {pad_x}px;"
            f"font-size: {font_size}px; font-family: \"{font_family}\";"
            f"}}"
            f"#vocabButton:hover {{ background-color: {C.COLORS['jp_button_secondary_hover']}; }}"
            f"#vocabButton:pressed {{ background-color: {C.COLORS['jp_button_secondary_border']}; }}"
        )

    def _compute_geometry(
        self, anchor: QPoint, bubble_rect: QRect, pointing_down: bool
    ) -> QRect:
        """按设计 §3.1 计算按钮条几何（水平居中于 anchor.x，紧贴气泡尾尖侧，屏幕钳制）。"""

        w = self.width()
        h = self.height()
        cx = anchor.x()

        if pointing_down:
            # 气泡在宠物上方、尾巴朝下 → 按钮条在气泡下方
            y = bubble_rect.bottom() + C.JP_BUTTON_BAR_GAP_PX
        else:
            # 气泡翻转到下方、尾巴朝上 → 按钮条在气泡上方
            y = bubble_rect.top() - C.JP_BUTTON_BAR_GAP_PX - h

        x = cx - w // 2

        screen = QGuiApplication.screenAt(anchor)
        if screen is None:
            screen = QGuiApplication.primaryScreen()
        if screen is not None:
            avail = screen.availableGeometry()
            x = max(avail.left(), min(x, avail.right() - w))
            y = max(avail.top(), min(y, avail.bottom() - h))

        return QRect(x, y, w, h)

    def _update_alpha(self) -> None:
        """按相位推进透明度（与气泡淡入/停留/淡出完全同步）。"""

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
                self.hide_bar()
                return

        self.setWindowOpacity(max(0.0, min(1.0, self._alpha)))
        self.update()


__all__ = ["BubbleButtonBar"]
