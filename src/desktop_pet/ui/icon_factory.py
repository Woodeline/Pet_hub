"""ui.icon_factory —— 程序化矢量图标工厂（延续「零外部素材」承诺）。

项目红线：**不落盘任何图片素材文件**（``test_no_image_assets`` 守护）。本模块全部用
``QPainterPath`` + ``QPainter`` 在**内存**里绘制到透明 ``QPixmap``，再包装为 ``QIcon``。

设计要点（对应计划 §3.2）：
- 画布 24×24，**内容限制在 2..22 的 20×20 安全区**内；线性（描边）风格，
  ``QPen`` 宽度 2、``RoundCap`` / ``RoundJoin``、开启抗锯齿。
- 默认描边色取 ``SEMANTIC_COLORS["text_secondary"]``，可由 ``color`` 覆盖。
- 未知图标名 → ``raise ValueError``。
- **禁止模块级立即创建 QPixmap / QIcon**（会要求 QApplication 已存在）；
  一切在 :func:`make_icon` 调用时**惰性创建**。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from desktop_pet.core import constants as C

#: 支持的图标名（与 :func:`make_icon` 的分发一一对应）。
ICON_NAMES: Final[tuple[str, ...]] = (
    "close",
    "retry",
    "refresh",
    "remove",
    "trash",
    "chevron_down",
)

#: 设计栅格边长（所有路径都在 0.._GRID 的坐标系里定义，绘制时按 size 缩放）。
_GRID: Final[float] = 24.0
#: 描边宽度（设计栅格单位；size=24 时为 2px）。
_PEN_W: Final[float] = 2.0


def _path_close() -> QPainterPath:
    """``close``：两条交叉线构成的 ×（关闭）。"""

    path = QPainterPath()
    path.moveTo(7.0, 7.0)
    path.lineTo(17.0, 17.0)
    path.moveTo(17.0, 7.0)
    path.lineTo(7.0, 17.0)
    return path


def _path_retry() -> QPainterPath:
    """``retry``：一段顺时针回转弧 + 单个箭头（重试）。"""

    path = QPainterPath()
    rect = QRectF(6.0, 6.0, 12.0, 12.0)
    path.arcMoveTo(rect, 55.0)
    path.arcTo(rect, 55.0, -300.0)
    # 起点处补一个「>」形箭头，表示旋转方向。
    path.moveTo(11.0, 3.0)
    path.lineTo(14.5, 5.5)
    path.lineTo(11.0, 8.0)
    return path


def _path_refresh() -> QPainterPath:
    """``refresh``：上下两段弧 + 两个箭头构成循环（刷新）。"""

    path = QPainterPath()
    rect = QRectF(6.0, 6.0, 12.0, 12.0)
    # 上半弧（逆时针）+ 右侧箭头
    path.arcMoveTo(rect, 30.0)
    path.arcTo(rect, 30.0, 150.0)
    path.moveTo(16.5, 5.5)
    path.lineTo(19.0, 9.0)
    path.lineTo(15.5, 10.0)
    # 下半弧（逆时针）+ 左侧箭头
    path.arcMoveTo(rect, 210.0)
    path.arcTo(rect, 210.0, 150.0)
    path.moveTo(7.5, 18.5)
    path.lineTo(5.0, 15.0)
    path.lineTo(8.5, 14.0)
    return path


def _path_remove() -> QPainterPath:
    """``remove``：圆形描边 + 居中减号（移除）。"""

    path = QPainterPath()
    path.addEllipse(QRectF(5.0, 5.0, 14.0, 14.0))
    path.moveTo(8.5, 12.0)
    path.lineTo(15.5, 12.0)
    return path


def _path_trash() -> QPainterPath:
    """``trash``：桶盖 + 提手 + 桶身 + 两根内竖线（清空/删除）。"""

    path = QPainterPath()
    # 桶盖横线
    path.moveTo(5.0, 7.0)
    path.lineTo(19.0, 7.0)
    # 提手
    path.moveTo(9.5, 7.0)
    path.lineTo(9.5, 5.0)
    path.lineTo(14.5, 5.0)
    path.lineTo(14.5, 7.0)
    # 桶身（梯形）
    path.moveTo(7.0, 7.0)
    path.lineTo(8.0, 19.0)
    path.lineTo(16.0, 19.0)
    path.lineTo(17.0, 7.0)
    # 内竖线
    path.moveTo(10.5, 10.0)
    path.lineTo(10.5, 16.0)
    path.moveTo(13.5, 10.0)
    path.lineTo(13.5, 16.0)
    return path


def _path_chevron_down() -> QPainterPath:
    """``chevron_down``：向下指的折线（展开/更多）。"""

    path = QPainterPath()
    path.moveTo(7.0, 10.0)
    path.lineTo(12.0, 15.0)
    path.lineTo(17.0, 10.0)
    return path


#: 图标名 → 路径构造函数（模块级只登记函数，不创建任何 Qt 绘图对象）。
_PATH_BUILDERS: Final[dict[str, Callable[[], QPainterPath]]] = {
    "close": _path_close,
    "retry": _path_retry,
    "refresh": _path_refresh,
    "remove": _path_remove,
    "trash": _path_trash,
    "chevron_down": _path_chevron_down,
}


def make_icon(name: str, color: str | None = None, size: int = 24) -> QIcon:
    """按名生成一个矢量 ``QIcon``。

    Args:
        name: 图标名，必须是 :data:`ICON_NAMES` 之一，否则抛 ``ValueError``。
        color: 描边色（``#RRGGBB``）；``None`` 时取
            ``SEMANTIC_COLORS["text_secondary"]``。
        size: 画布边长（px），默认 24。

    Returns:
        一个非空的 :class:`QIcon`（内部为透明底 + 描边图形，全程内存绘制）。
    """

    if name not in ICON_NAMES:
        raise ValueError(f"未知图标名：{name!r}（可选：{', '.join(ICON_NAMES)}）")

    safe_size = max(1, int(size))
    pen_color = color if color is not None else C.SEMANTIC_COLORS["text_secondary"]

    pixmap = QPixmap(safe_size, safe_size)
    pixmap.fill(Qt.GlobalColor.transparent)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(pen_color))
    pen.setWidthF(_PEN_W)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # 把 24×24 设计坐标系缩放到目标尺寸，再绘制对应路径。
    scale = safe_size / _GRID
    painter.scale(scale, scale)
    painter.drawPath(_PATH_BUILDERS[name]())

    painter.end()
    return QIcon(pixmap)


__all__ = ["ICON_NAMES", "make_icon"]
