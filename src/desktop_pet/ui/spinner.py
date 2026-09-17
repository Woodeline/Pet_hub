"""ui.spinner —— 程序化旋转加载指示器（QPainter 绘制，零外部素材）。

用途：单词详情窗「联网查询中…」时，在状态标签旁显示一个旋转弧（文字仍保留）。

设计约束（对应计划 §4）：
- 用 ``QPainter`` 画旋转弧（12 段渐隐），``QTimer`` 驱动；**每 tick 只做** ``self.update()``，
  不触碰其它窗口。
- ``QTimer`` **必须挂 parent**（``QTimer(self)``），并在 ``hideEvent`` / ``closeEvent`` 里
  ``stop()``，随父控件一同释放（避免 ``test_memory_budget`` 检测到 QTimer 泄漏）。
- ``reduce_motion=True`` 时**不启动 QTimer**，只画一个静态弧（不播放动画）。
- 尺寸默认 16×16、居中、透明底、无背景。
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget

from desktop_pet.core import constants as C

#: 旋转刷新间隔（ms）。
_TICK_INTERVAL_MS: int = 80
#: 弧段数量（12 段 = 每段 30°）。
_SEGMENTS: int = 12
#: 每段弧张角（度）。
_ARC_SPAN_DEG: int = 22
#: 描边宽度（px）。
_PEN_W: float = 2.0


class Spinner(QWidget):
    """旋转加载指示器（透明底、居中弧）。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        size: int = 16,
        reduce_motion: bool = False,
    ) -> None:
        """构造指示器。

        Args:
            parent: 父控件（QTimer 会挂到它下面以随其释放）。
            size: 边长（px，正方形）。
            reduce_motion: 「减少动效」开关；``True`` 时不启动计时器（画静态弧）。
        """

        super().__init__(parent)
        self._size: int = max(4, int(size))
        self._reduce_motion: bool = bool(reduce_motion)
        self._angle_deg: int = 0
        self._spinning: bool = False

        self.setFixedSize(self._size, self._size)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        # 计时器必须挂 parent（self），随控件析构自动释放。
        self._timer = QTimer(self)
        self._timer.setInterval(_TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        """开始旋转（减少动效时不启动计时器，仅刷新为静态弧）。"""

        if self._reduce_motion:
            self._spinning = False
            self.update()
            return
        self._spinning = True
        self._timer.start()
        self.update()

    def stop(self) -> None:
        """停止旋转。"""

        self._spinning = False
        self._timer.stop()
        self.update()

    def is_spinning(self) -> bool:
        """是否正在旋转。"""

        return self._spinning

    def set_reduce_motion(self, flag: bool) -> None:
        """更新「减少动效」开关；置为 ``True`` 时立即停止旋转。"""

        self._reduce_motion = bool(flag)
        if self._reduce_motion:
            self.stop()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _on_tick(self) -> None:
        """每 tick 仅推进角度并请求重绘。"""

        self._angle_deg = (self._angle_deg + 30) % 360
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """绘制 12 段渐隐弧（``_angle_deg`` 决定起始朝向）。"""

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        inset = _PEN_W + 1.0
        rect = QRectF(
            inset, inset, self._size - 2.0 * inset, self._size - 2.0 * inset
        )

        base = QColor(C.SEMANTIC_COLORS["info"])
        pen = QPen(base)
        pen.setWidthF(_PEN_W)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)

        for index in range(_SEGMENTS):
            color = QColor(base)
            # 越靠近「头部」越不透明 → 形成渐隐拖尾。
            color.setAlpha(int(255 * (index + 1) / _SEGMENTS))
            pen.setColor(color)
            painter.setPen(pen)
            start_angle = int((self._angle_deg + index * 30) * 16)
            painter.drawArc(rect, start_angle, int(_ARC_SPAN_DEG * 16))

        painter.end()

    def hideEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """隐藏即停止（避免后台空转）。"""

        self.stop()
        super().hideEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """关闭即停止计时器。"""

        self.stop()
        super().closeEvent(event)


__all__ = ["Spinner"]
