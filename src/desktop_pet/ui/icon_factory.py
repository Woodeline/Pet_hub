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
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap

from desktop_pet.core import constants as C

#: 支持的图标名（与 :func:`make_icon` 的分发一一对应）。
ICON_NAMES: Final[tuple[str, ...]] = (
    "close",
    "retry",
    "remove",
    "trash",
    "speaker",
    "pencil",
)

#: 设计栅格边长（所有路径都在 0.._GRID 的坐标系里定义，绘制时按 size 缩放）。
_GRID: Final[float] = 24.0
#: 描边宽度（设计栅格单位；size=24 时为 2px）。
_PEN_W: Final[float] = 2.0


def screen_dpr() -> float:
    """主屏设备像素比（Retina=2）；无 QApplication/屏幕时回退 1。"""

    app = QGuiApplication.instance()
    screen = app.primaryScreen() if app is not None else None
    return float(screen.devicePixelRatio()) if screen is not None else 1.0


def _render_icon_pixmap(
    builder: Callable[[], QPainterPath], pen_color: str, px: int, dpr: float
) -> QPixmap:
    """按物理像素（px × dpr）渲染矢量路径并打上 DPR 标记。

    Retina 下若只按逻辑像素出图，位图被拉伸一倍 → 图标发糊；
    物理 2x 出图 + setDevicePixelRatio 后，QPainter/QIcon 按逻辑尺寸
    采样高密度位图，边缘锐利。
    """

    safe_size = max(1, int(px))
    ratio = max(1.0, float(dpr))
    physical = max(1, int(round(safe_size * ratio)))

    pixmap = QPixmap(physical, physical)
    pixmap.fill(Qt.GlobalColor.transparent)
    pixmap.setDevicePixelRatio(ratio)

    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(QColor(pen_color))
    pen.setWidthF(_PEN_W)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    # 带 DPR 标记的位图上 QPainter 以逻辑像素为单位：缩放必须用逻辑边长，
    # 用物理边长会把路径画出画布、位图只剩左上角（Retina 图标显示不全根因）。
    painter.scale(safe_size / _GRID, safe_size / _GRID)
    painter.drawPath(builder())
    painter.end()
    return pixmap


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


def _path_speaker() -> QPainterPath:
    """``speaker``：喇叭箱体 + 锥面 + 两道声波弧（发音占位，功能未启用）。"""

    path = QPainterPath()
    # 箱体（左半矩形）+ 锥面（上下顶点收拢成梯形喇叭口）
    path.moveTo(5.0, 9.5)
    path.lineTo(9.0, 9.5)
    path.lineTo(13.5, 5.0)
    path.lineTo(13.5, 19.0)
    path.lineTo(9.0, 14.5)
    path.lineTo(5.0, 14.5)
    path.closeSubpath()
    # 两道声波弧（只画右侧，圆心 (16,12)，r=4 / r=6，右缘不越出 22 安全线）
    for radius in (4.0, 6.0):
        rect = QRectF(16.0 - radius, 12.0 - radius, radius * 2.0, radius * 2.0)
        path.arcMoveTo(rect, -50.0)
        path.arcTo(rect, -50.0, 100.0)
    return path


def _path_pencil() -> QPainterPath:
    """``pencil``：斜置铅笔（笔杆 + 笔尖三角 + 笔尾端帽 + 分界线）——纠错入口。"""

    path = QPainterPath()
    # 闭合轮廓：笔尖（左下）→ 笔杆上边 → 笔尾端帽 → 笔杆下边 → 回到笔尖
    path.moveTo(4.5, 19.5)   # 笔尖
    path.lineTo(15.0, 9.0)   # 上边
    path.lineTo(17.5, 11.5)  # 笔尾端帽（垂直于笔杆方向）
    path.lineTo(7.0, 22.0)   # 下边
    path.closeSubpath()      # 笔尖三角自动闭合
    # 笔尖与笔杆的分界线（沿垂直方向平移出一小段）
    path.moveTo(13.9, 10.1)
    path.lineTo(16.4, 12.6)
    return path


#: 图标名 → 路径构造函数（模块级只登记函数，不创建任何 Qt 绘图对象）。
_PATH_BUILDERS: Final[dict[str, Callable[[], QPainterPath]]] = {
    "close": _path_close,
    "retry": _path_retry,
    "remove": _path_remove,
    "trash": _path_trash,
    "speaker": _path_speaker,
    "pencil": _path_pencil,
}


def make_icon(name: str, color: str | None = None, size: int = 24, dpr: float | None = None) -> QIcon:
    """按名生成一个矢量 ``QIcon``。

    Args:
        name: 图标名，必须是 :data:`ICON_NAMES` 之一，否则抛 ``ValueError``。
        color: 描边色（``#RRGGBB``）；``None`` 时取
            ``SEMANTIC_COLORS["text_secondary"]``。
        size: 画布边长（逻辑 px），默认 24。
        dpr: 设备像素比；``None`` 取主屏 DPR（Retina 自动 2x 出图防糊）。

    Returns:
        一个非空的 :class:`QIcon`（内部为透明底 + 描边图形，全程内存绘制）。
    """

    if name not in ICON_NAMES:
        raise ValueError(f"未知图标名：{name!r}（可选：{', '.join(ICON_NAMES)}）")

    pen_color = color if color is not None else C.SEMANTIC_COLORS["text_secondary"]
    pixmap = _render_icon_pixmap(
        _PATH_BUILDERS[name], pen_color, size, dpr if dpr is not None else screen_dpr()
    )
    return QIcon(pixmap)


# --------------------------------------------------------------------------- #
# 菜单行图标（右键菜单精致化）—— 独立注册表，**不**并入 ICON_NAMES / make_icon
# （后者的六图标清单被 test_icon_factory 全等钉死）。同一 24 栅格 / 线性描边语言，
# 默认 16px（C.MENU_ICON_PX），供 tray 菜单逐行 setIcon；退出取 destructive 红。
# --------------------------------------------------------------------------- #

#: 菜单图标名清单（与 :func:`menu_icon` 分发一一对应）。
#: 命令 / 子菜单父行图标经 ``QAction.setIcon`` 上托盘；开关行图标（keyboard/bubble/
#: power/wind）**只由富条目 widget 自绘**、不 setIcon 到 QAction——Qt 在动作带图标时
#: 会丢弃勾选标记，故开关的 QAction 保持无图标以保留原生托盘勾选。
MENU_ICON_NAMES: Final[tuple[str, ...]] = (
    "pet", "minimize", "edit", "book", "database",
    "refresh", "scale", "palette", "skin", "quit",
    "eye", "bookmark", "check", "log", "calendar", "review", "level",
    "chart", "import", "clock",
    "keyboard", "bubble", "power", "wind",
)


def _m_pet() -> QPainterPath:
    """``pet``：猫脸（圆头 + 双耳 + 两点眼）——显示宠物，呼应小喵酱本体。"""

    p = QPainterPath()
    p.addEllipse(QRectF(6.0, 8.5, 12.0, 11.0))
    p.moveTo(7.5, 9.6); p.lineTo(6.0, 4.5); p.lineTo(10.6, 7.9)
    p.moveTo(16.5, 9.6); p.lineTo(18.0, 4.5); p.lineTo(13.4, 7.9)
    p.moveTo(9.7, 13.0); p.lineTo(9.7, 14.2)
    p.moveTo(14.3, 13.0); p.lineTo(14.3, 14.2)
    return p


def _m_minimize() -> QPainterPath:
    """``minimize``：向下箭头落入托盘横栏——最小化到托盘。"""

    p = QPainterPath()
    p.moveTo(12.0, 4.0); p.lineTo(12.0, 13.5)
    p.moveTo(8.0, 9.5); p.lineTo(12.0, 13.5); p.lineTo(16.0, 9.5)
    p.moveTo(5.0, 15.5); p.lineTo(5.0, 18.5); p.lineTo(19.0, 18.5); p.lineTo(19.0, 15.5)
    return p


def _m_book() -> QPainterPath:
    """``book``：摊开的书（左右两页 + 中缝书脊）——日语学习。"""

    p = QPainterPath()
    p.moveTo(12.0, 7.5)
    p.cubicTo(9.0, 6.0, 6.0, 6.0, 4.0, 6.8)
    p.lineTo(4.0, 17.5)
    p.cubicTo(6.0, 16.7, 9.0, 16.7, 12.0, 18.2)
    p.moveTo(12.0, 7.5)
    p.cubicTo(15.0, 6.0, 18.0, 6.0, 20.0, 6.8)
    p.lineTo(20.0, 17.5)
    p.cubicTo(18.0, 16.7, 15.0, 16.7, 12.0, 18.2)
    p.moveTo(12.0, 7.5); p.lineTo(12.0, 18.2)
    return p


def _m_database() -> QPainterPath:
    """``database``：圆柱数据库（顶椭圆 + 侧壁 + 两道底弧）——数据管理。"""

    p = QPainterPath()
    p.addEllipse(QRectF(5.0, 4.5, 14.0, 5.0))
    p.moveTo(5.0, 7.0); p.lineTo(5.0, 17.0)
    p.moveTo(19.0, 7.0); p.lineTo(19.0, 17.0)
    p.moveTo(5.0, 12.0); p.cubicTo(5.0, 14.5, 19.0, 14.5, 19.0, 12.0)
    p.moveTo(5.0, 17.0); p.cubicTo(5.0, 19.5, 19.0, 19.5, 19.0, 17.0)
    return p


def _m_scale() -> QPainterPath:
    """``scale``：对角双向箭头 + 两角框——大小（缩放）。"""

    p = QPainterPath()
    p.moveTo(4.0, 9.0); p.lineTo(4.0, 4.0); p.lineTo(9.0, 4.0)
    p.moveTo(20.0, 15.0); p.lineTo(20.0, 20.0); p.lineTo(15.0, 20.0)
    p.moveTo(8.0, 16.0); p.lineTo(16.0, 8.0)
    p.moveTo(16.0, 12.0); p.lineTo(16.0, 8.0); p.lineTo(12.0, 8.0)
    p.moveTo(8.0, 12.0); p.lineTo(8.0, 16.0); p.lineTo(12.0, 16.0)
    return p


def _m_palette() -> QPainterPath:
    """``palette``：调色盘（椭圆盘 + 拇指孔 + 三颜料点）——主题配色。"""

    p = QPainterPath()
    p.addEllipse(QRectF(4.0, 5.0, 16.0, 14.0))
    p.addEllipse(QRectF(12.3, 12.3, 3.4, 3.4))
    for x, y in ((8.0, 9.5), (11.0, 7.6), (15.0, 9.0)):
        p.moveTo(x, y); p.lineTo(x, y + 0.2)
    return p


def _m_skin() -> QPainterPath:
    """``skin``：四角星芒 + 右下小星——皮肤（MOD）焕新。"""

    p = QPainterPath()
    p.moveTo(11.0, 3.5)
    p.cubicTo(11.0, 8.0, 11.0, 8.0, 16.5, 10.0)
    p.cubicTo(11.0, 12.0, 11.0, 12.0, 11.0, 16.5)
    p.cubicTo(11.0, 12.0, 11.0, 12.0, 5.5, 10.0)
    p.cubicTo(11.0, 8.0, 11.0, 8.0, 11.0, 3.5)
    p.closeSubpath()
    p.moveTo(17.5, 14.0); p.lineTo(17.5, 19.0)
    p.moveTo(15.0, 16.5); p.lineTo(20.0, 16.5)
    return p


def _m_quit() -> QPainterPath:
    """``quit``：登出（左门框 + 向右离开的箭头）——退出（红色）。"""

    p = QPainterPath()
    p.moveTo(12.0, 4.0); p.lineTo(6.0, 4.0); p.lineTo(6.0, 20.0); p.lineTo(12.0, 20.0)
    p.moveTo(10.0, 12.0); p.lineTo(20.0, 12.0)
    p.moveTo(16.5, 8.5); p.lineTo(20.0, 12.0); p.lineTo(16.5, 15.5)
    return p


def _m_eye() -> QPainterPath:
    """``eye``：眼睛轮廓 + 瞳孔——立即显示。"""

    p = QPainterPath()
    p.moveTo(3.5, 12.0)
    p.cubicTo(7.0, 6.5, 17.0, 6.5, 20.5, 12.0)
    p.cubicTo(17.0, 17.5, 7.0, 17.5, 3.5, 12.0)
    p.closeSubpath()
    p.addEllipse(QRectF(9.5, 9.5, 5.0, 5.0))
    return p


def _m_bookmark() -> QPainterPath:
    """``bookmark``：书签丝带——生词本。"""

    p = QPainterPath()
    p.moveTo(7.0, 4.0); p.lineTo(17.0, 4.0); p.lineTo(17.0, 20.0)
    p.lineTo(12.0, 16.0); p.lineTo(7.0, 20.0); p.closeSubpath()
    return p


def _m_check() -> QPainterPath:
    """``check``：圆环 + 对勾——已掌握。"""

    p = QPainterPath()
    p.addEllipse(QRectF(4.0, 4.0, 16.0, 16.0))
    p.moveTo(8.0, 12.0); p.lineTo(11.0, 15.0); p.lineTo(16.0, 9.0)
    return p


def _m_log() -> QPainterPath:
    """``log``：文档页 + 三条记录线——学习记录。"""

    p = QPainterPath()
    p.addRoundedRect(QRectF(5.0, 3.5, 14.0, 17.0), 2.0, 2.0)
    p.moveTo(8.0, 8.0); p.lineTo(16.0, 8.0)
    p.moveTo(8.0, 12.0); p.lineTo(16.0, 12.0)
    p.moveTo(8.0, 16.0); p.lineTo(13.0, 16.0)
    return p


def _m_calendar() -> QPainterPath:
    """``calendar``：日历（顶部分栏 + 两装订脚 + 中心点）——每日数量。"""

    p = QPainterPath()
    p.addRoundedRect(QRectF(4.0, 5.0, 16.0, 15.0), 2.0, 2.0)
    p.moveTo(4.0, 9.5); p.lineTo(20.0, 9.5)
    p.moveTo(8.0, 3.5); p.lineTo(8.0, 6.5)
    p.moveTo(16.0, 3.5); p.lineTo(16.0, 6.5)
    p.moveTo(12.0, 14.0); p.lineTo(12.0, 14.2)
    return p


def _m_review() -> QPainterPath:
    """``review``：上下两条反向箭头——复习上限（间隔重复）。"""

    p = QPainterPath()
    p.moveTo(5.0, 9.0); p.lineTo(16.0, 9.0)
    p.moveTo(13.0, 6.0); p.lineTo(16.0, 9.0); p.lineTo(13.0, 12.0)
    p.moveTo(19.0, 15.0); p.lineTo(8.0, 15.0)
    p.moveTo(11.0, 12.0); p.lineTo(8.0, 15.0); p.lineTo(11.0, 18.0)
    return p


def _m_level() -> QPainterPath:
    """``level``：三根递增竖条——难度档位。"""

    p = QPainterPath()
    p.moveTo(6.0, 19.0); p.lineTo(6.0, 15.0)
    p.moveTo(11.0, 19.0); p.lineTo(11.0, 11.0)
    p.moveTo(16.0, 19.0); p.lineTo(16.0, 7.0)
    return p


def _m_chart() -> QPainterPath:
    """``chart``：L 形坐标轴 + 三根柱——学习统计。"""

    p = QPainterPath()
    p.moveTo(4.5, 4.0); p.lineTo(4.5, 20.0); p.lineTo(20.0, 20.0)
    p.moveTo(8.5, 20.0); p.lineTo(8.5, 14.0)
    p.moveTo(12.5, 20.0); p.lineTo(12.5, 9.0)
    p.moveTo(16.5, 20.0); p.lineTo(16.5, 12.0)
    return p


def _m_import() -> QPainterPath:
    """``import``：向下箭头落入 U 形托盘——导入词库。"""

    p = QPainterPath()
    p.moveTo(12.0, 4.0); p.lineTo(12.0, 14.0)
    p.moveTo(8.0, 10.5); p.lineTo(12.0, 14.5); p.lineTo(16.0, 10.5)
    p.moveTo(5.0, 16.0); p.lineTo(5.0, 19.0); p.lineTo(19.0, 19.0); p.lineTo(19.0, 16.0)
    return p


def _m_clock() -> QPainterPath:
    """``clock``：钟面 + 时针分针——显示时长。"""

    p = QPainterPath()
    p.addEllipse(QRectF(4.5, 4.5, 15.0, 15.0))
    p.moveTo(12.0, 12.0); p.lineTo(12.0, 7.5)
    p.moveTo(12.0, 12.0); p.lineTo(15.5, 13.0)
    return p


def _m_keyboard() -> QPainterPath:
    """``keyboard``：键盘外框 + 键位点 + 空格条——监听键盘（开关行自绘）。"""

    p = QPainterPath()
    p.addRoundedRect(QRectF(3.0, 6.5, 18.0, 11.0), 1.5, 1.5)
    for x in (6.5, 10.0, 13.5, 17.0):
        p.moveTo(x, 10.0); p.lineTo(x, 10.2)
    p.moveTo(7.5, 14.0); p.lineTo(16.5, 14.0)
    return p


def _m_bubble() -> QPainterPath:
    """``bubble``：对话气泡 + 左下尾尖——气泡提示（开关行自绘）。"""

    p = QPainterPath()
    p.moveTo(4.0, 5.5); p.lineTo(20.0, 5.5); p.lineTo(20.0, 15.0)
    p.lineTo(9.5, 15.0); p.lineTo(5.0, 19.5); p.lineTo(5.0, 15.0)
    p.lineTo(4.0, 15.0); p.closeSubpath()
    return p


def _m_power() -> QPainterPath:
    """``power``：电源符（竖线 + 开口圆弧）——开机自启（开关行自绘）。"""

    p = QPainterPath()
    p.moveTo(12.0, 3.5); p.lineTo(12.0, 12.0)
    p.arcTo(QRectF(4.4, 4.4, 15.2, 15.2), 130.0, 280.0)
    return p


def _m_wind() -> QPainterPath:
    """``wind``：三道气流线（末端回勾）——减少动效（开关行自绘）。"""

    p = QPainterPath()
    p.moveTo(3.0, 8.0); p.lineTo(13.0, 8.0)
    p.cubicTo(16.0, 8.0, 16.0, 4.0, 13.0, 4.0)
    p.moveTo(3.0, 12.0); p.lineTo(17.0, 12.0)
    p.cubicTo(20.0, 12.0, 20.0, 16.0, 17.0, 16.0)
    p.moveTo(3.0, 16.0); p.lineTo(10.0, 16.0)
    p.cubicTo(12.5, 16.0, 12.5, 19.0, 10.0, 19.0)
    return p


#: 菜单图标名 → 路径构造函数（``edit``/``refresh`` 复用既有铅笔 / 回转弧路径）。
_MENU_PATH_BUILDERS: Final[dict[str, Callable[[], QPainterPath]]] = {
    "pet": _m_pet,
    "minimize": _m_minimize,
    "edit": _path_pencil,
    "book": _m_book,
    "database": _m_database,
    "refresh": _path_retry,
    "scale": _m_scale,
    "palette": _m_palette,
    "skin": _m_skin,
    "quit": _m_quit,
    "eye": _m_eye,
    "bookmark": _m_bookmark,
    "check": _m_check,
    "log": _m_log,
    "calendar": _m_calendar,
    "review": _m_review,
    "level": _m_level,
    "chart": _m_chart,
    "import": _m_import,
    "clock": _m_clock,
    "keyboard": _m_keyboard,
    "bubble": _m_bubble,
    "power": _m_power,
    "wind": _m_wind,
}


def menu_icon_pixmap(
    name: str, color: str | None = None, px: int = C.MENU_ICON_PX, dpr: float | None = None
) -> QPixmap:
    """按名生成菜单行矢量位图（DPR 感知，Retina 2x 出图防糊）。

    供富行 widget 直接 ``drawPixmap``（带 DPR 标记的位图按逻辑尺寸采样，
    边缘锐利）；:func:`menu_icon` 亦复用它包装 ``QIcon``。
    """

    if name not in MENU_ICON_NAMES:
        raise ValueError(f"未知菜单图标名：{name!r}（可选：{', '.join(MENU_ICON_NAMES)}）")

    pen_color = color if color is not None else C.SEMANTIC_COLORS["text_secondary"]
    return _render_icon_pixmap(
        _MENU_PATH_BUILDERS[name], pen_color, px, dpr if dpr is not None else screen_dpr()
    )


def menu_icon(name: str, color: str | None = None, px: int = C.MENU_ICON_PX) -> QIcon:
    """按名生成一个菜单行矢量 ``QIcon``（默认 16px，线性描边，全程内存绘制）。

    Args:
        name: 图标名，必须是 :data:`MENU_ICON_NAMES` 之一，否则抛 ``ValueError``。
        color: 描边色（``#RRGGBB``）；``None`` 取 ``SEMANTIC_COLORS["text_secondary"]``。
            退出图标由调用方传 ``SEMANTIC_COLORS["destructive"]`` 染红。
        px: 画布边长（逻辑 px），默认 ``C.MENU_ICON_PX``（16）。

    Returns:
        非空 :class:`QIcon`（透明底 + 描边图形，主屏 DPR 自动 2x）。与
        :func:`make_icon` 共用绘图语言，但注册表独立——菜单图标集扩张不影响
        按钮六图标的清单守卫。
    """

    return QIcon(menu_icon_pixmap(name, color, px))


__all__ = ["ICON_NAMES", "make_icon", "MENU_ICON_NAMES", "menu_icon", "menu_icon_pixmap", "screen_dpr"]
