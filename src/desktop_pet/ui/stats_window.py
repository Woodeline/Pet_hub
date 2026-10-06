"""ui.stats_window —— 只读「学习统计」窗口（统计面板，纯展示）。

仅负责展示，**不直接读写存储**（数据由 ``app/controller`` 经
``core.stats_aggregator.build_summary`` 聚合后喂入 :meth:`StatsWindow.refresh`）。

- 顶部概览卡：连续打卡 / 累计掌握 / 今日新词 x/y / 今日复习 x/y。
- 中部：学习热力图（近 15 周，QPainter 色块网格）+ 掌握曲线（累计折线）。
  图表全部 QPainter 自绘（项目零 matplotlib 依赖）；色值一律出自
  ``core.constants`` 的 token（含 ``QColor`` alpha 变体），不写裸色值。
"""

from __future__ import annotations

import logging
from datetime import date

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.core import constants as C
from desktop_pet.core.stats_aggregator import StatsSummary
from desktop_pet.ui import icon_factory, motion_ui, theme

logger = logging.getLogger(__name__)


def _level_color(level: int) -> QColor:
    """热力图色阶 → 颜色（基色全部出自 token；0 档为浅灰空格）。"""

    if level <= 0:
        return QColor(C.COLORS["bubble_divider"])
    color = QColor(C.SEMANTIC_COLORS["success"])
    if level == 1:
        color.setAlpha(90)
    elif level == 2:
        color.setAlpha(170)
    return color


def _level_for(count: int) -> int:
    """当日学习量 → 色阶档位（0 空格 / 1 浅 / 2 中 / 3 浓，阈值见常量）。"""

    if count <= 0:
        return 0
    if count <= C.STATS_HEATMAP_LEVEL1_MAX:
        return 1
    if count <= C.STATS_HEATMAP_LEVEL2_MAX:
        return 2
    return 3


class _Heatmap(QWidget):
    """学习热力图：GitHub 风格色块网格（列 = 周，行 = 周一..周日）。"""

    #: 单元格逻辑尺寸 / 间距 / 圆角（几何参数，非颜色 token）
    _CELL_MIN: float = 9.0
    _CELL_MAX: float = 16.0
    _CELL_GAP: float = 3.0
    _CELL_RADIUS: float = 2.0
    _LEFT_PAD: float = 20.0   # 行标签（一~日）宽度
    _TOP_PAD: float = 4.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._counts: dict[str, int] = {}
        self._day_keys: tuple[str, ...] = ()
        self._cells: list[tuple[float, float, str, int]] = []  # (x, y, day, level)
        self.setMinimumHeight(124)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    def set_data(self, counts: dict[str, int], day_keys: tuple[str, ...]) -> None:
        """喂入每日学习量与升序日期 key（controller 每次打开窗口时调用）。"""

        self._counts = dict(counts)
        self._day_keys = tuple(str(key) for key in day_keys)
        self._recompute_cells()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """窗口拉伸后按新宽度重排格子（保持与 ``_cell_size`` 同一公式）。"""

        super().resizeEvent(event)
        self._recompute_cells()
        self.update()

    def _cell_size(self) -> float:
        """当前单元格边长（宽度自适应，限定在 ``[_CELL_MIN, _CELL_MAX]``）。"""

        width = max(0.0, self.width() - self._LEFT_PAD - self._TOP_PAD)
        weeks = max(1, C.STATS_HEATMAP_WEEKS)
        return max(
            self._CELL_MIN,
            min(self._CELL_MAX, (width - self._CELL_GAP * (weeks - 1)) / weeks),
        )

    def _recompute_cells(self) -> None:
        """按当前控件宽度重算每个日期格的像素位置。"""

        self._cells = []
        if not self._day_keys:
            return
        try:
            origin = date.fromisoformat(self._day_keys[0])
        except ValueError:
            return
        cell = self._cell_size()
        for day in self._day_keys:
            try:
                parsed = date.fromisoformat(day)
            except ValueError:
                continue
            col = (parsed - origin).days // 7
            row = parsed.isoweekday() - 1  # 周一 = 0（与 STATS_WEEKDAY_LABELS 同序）
            x = self._LEFT_PAD + col * (cell + self._CELL_GAP)
            y = self._TOP_PAD + row * (cell + self._CELL_GAP)
            self._cells.append((x, y, day, _level_for(int(self._counts.get(day, 0)))))

    def paintEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        if not self._cells:
            return
        cell = self._cell_size()
        # 行标签（周一 → 周日）
        painter.setPen(QColor(C.SEMANTIC_COLORS["text_faint"]))
        font = QFont(self.font())
        font.setPixelSize(C.FONT_SIZE["small"])
        painter.setFont(font)
        for row, label in enumerate(C.STATS_WEEKDAY_LABELS):
            y = self._TOP_PAD + row * (cell + self._CELL_GAP)
            painter.drawText(
                QRectF(0.0, y, self._LEFT_PAD - 6.0, cell),
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                label,
            )
        painter.setPen(Qt.PenStyle.NoPen)
        for x, y, _day, level in self._cells:
            painter.setBrush(_level_color(level))
            painter.drawRoundedRect(QRectF(x, y, cell, cell), self._CELL_RADIUS, self._CELL_RADIUS)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """悬停显示「MM-DD · N 次」提示（命中格才显示，其余走默认）。"""

        cell = self._cell_size()
        pos = event.position().toPoint()
        for x, y, day, _level in self._cells:
            if x <= pos.x() <= x + cell and y <= pos.y() <= y + cell:
                count = int(self._counts.get(day, 0))
                QToolTip.showText(
                    event.globalPosition().toPoint(), f"{day[5:]} · {count} 次", self
                )
                break
        super().mouseMoveEvent(event)


class _Curve(QWidget):
    """掌握曲线：累计已掌握折线（QPainter 自绘，含末端数值标注）。"""

    _PAD_L: float = 34.0
    _PAD_R: float = 12.0
    _PAD_T: float = 10.0
    _PAD_B: float = 18.0

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._points: tuple[tuple[str, int], ...] = ()
        self.setMinimumHeight(150)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def set_data(self, points: tuple[tuple[str, int], ...]) -> None:
        """喂入累计掌握曲线 ``((day, cumulative), ...)``（升序）。"""

        self._points = tuple(points)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        width = float(self.width())
        height = float(self.height())
        plot_w = max(1.0, width - self._PAD_L - self._PAD_R)
        plot_h = max(1.0, height - self._PAD_T - self._PAD_B)

        font = QFont(self.font())
        font.setPixelSize(C.FONT_SIZE["small"])
        painter.setFont(font)

        if not self._points:
            painter.setPen(QColor(C.SEMANTIC_COLORS["text_faint"]))
            painter.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, "—")
            return

        y_max = max(1, max(value for _day, value in self._points))
        # 横向淡网格（25% / 50% / 75% 三条）
        painter.setPen(QColor(C.COLORS["bubble_divider"]))
        for fraction in (0.25, 0.5, 0.75):
            y = self._PAD_T + plot_h * (1.0 - fraction)
            painter.drawLine(QPointF(self._PAD_L, y), QPointF(width - self._PAD_R, y))

        n = len(self._points)
        step_x = plot_w / max(1, n - 1)
        polyline = QPolygonF()
        for index, (_day, value) in enumerate(self._points):
            x = self._PAD_L + step_x * index
            y = self._PAD_T + plot_h * (1.0 - value / y_max)
            polyline.append(QPointF(x, y))

        # 折线（token 绿）+ 末端数值
        pen = QPen(QColor(C.SEMANTIC_COLORS["success"]))
        pen.setWidthF(2.0)
        painter.setPen(pen)
        painter.drawPolyline(polyline)

        last_x, last_y = polyline[-1].x(), polyline[-1].y()
        painter.setBrush(QColor(C.SEMANTIC_COLORS["success"]))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(last_x, last_y), 3.0, 3.0)
        painter.setPen(QColor(C.SEMANTIC_COLORS["text_secondary"]))
        painter.drawText(
            QRectF(last_x - 34.0, last_y - 22.0, 44.0, 16.0),
            Qt.AlignmentFlag.AlignCenter,
            str(self._points[-1][1]),
        )
        # X 轴端点日期（字符串切片取 MM-DD，不解析时间）
        painter.setPen(QColor(C.SEMANTIC_COLORS["text_faint"]))
        painter.drawText(
            QRectF(self._PAD_L - 12.0, height - self._PAD_B + 2.0, 60.0, 14.0),
            Qt.AlignmentFlag.AlignLeft,
            self._points[0][0][5:],
        )
        painter.drawText(
            QRectF(width - self._PAD_R - 60.0, height - self._PAD_B + 2.0, 60.0, 14.0),
            Qt.AlignmentFlag.AlignRight,
            self._points[-1][0][5:],
        )


class _StatBlock(QWidget):
    """概览卡中的一个统计块：大数值 + 小标题。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(C.SPACING["xs"])
        self._value_label = QLabel("—", self)
        self._value_label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['display']}px; font-weight: bold;"
            f" color: {C.SEMANTIC_COLORS['text_primary']}; background: transparent;"
        )
        title_label = QLabel(title, self)
        title_label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['caption']}px;"
            f" color: {C.SEMANTIC_COLORS['text_secondary']}; background: transparent;"
        )
        layout.addWidget(self._value_label)
        layout.addWidget(title_label)

    def set_value(self, text: str) -> None:
        """更新数值文案（由窗口在 refresh 时调用）。"""

        self._value_label.setText(str(text))


class StatsWindow(QWidget):
    """学习统计窗口（普通顶层窗口，纯展示）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        """构造学习统计窗口。"""

        super().__init__(parent)
        self.setWindowTitle(C.JP_STATS_WINDOW_TITLE)
        self.resize(C.JP_STATS_WINDOW_W, C.JP_STATS_WINDOW_H)
        self._reduce_motion: bool = False

        self._build_ui()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def refresh(
        self, summary: StatsSummary, new_limit: int, review_limit: int
    ) -> None:
        """由 controller 喂入聚合结果与当日两项目标上限并刷新显示。"""

        today = summary.day_keys[-1] if summary.day_keys else ""
        new_count = summary.new_words.get(today, 0)
        review_count = summary.review_ok.get(today, 0) + summary.review_lapsed.get(today, 0)
        self._streak_block.set_value(f"{summary.streak_days} {C.STATS_STREAK_UNIT}")
        self._mastered_block.set_value(f"{summary.total_mastered} {C.STATS_MASTERED_UNIT}")
        self._today_new_block.set_value(f"{new_count} / {int(new_limit)}")
        self._today_review_block.set_value(f"{review_count} / {int(review_limit)}")
        self._heatmap.set_data(summary.new_words, summary.day_keys)
        self._curve.set_data(summary.mastered_curve)
        has_any = (
            summary.total_mastered > 0
            or any(value > 0 for value in summary.new_words.values())
            or any(value > 0 for value in summary.review_ok.values())
            or any(value > 0 for value in summary.review_lapsed.values())
        )
        self._empty_hint.setVisible(not has_any)

    def set_reduce_motion(self, flag: bool) -> None:
        """注入「减少动效」开关（由 controller 在窗口显示前调用）。"""

        self._reduce_motion = bool(flag)

    def set_accent(self, accent: str | None) -> None:
        """应用主题点缀色（controller 在窗口创建与换肤时调用）。"""

        theme.apply_theme(self, accent)

    def closeEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """关闭：开启动效且窗口可见时先淡出再隐藏（与学习记录窗口一致）。"""

        if motion_ui.motion_enabled(self._reduce_motion) and self.isVisible():
            event.ignore()
            motion = motion_ui.create_window_motion(self, self._reduce_motion)
            motion.fade_out(on_finished=self.hide)
            return
        super().closeEvent(event)

    # ------------------------------------------------------------------ #
    # UI 构建
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        """构建界面元素与布局。"""

        theme.apply_theme(self)
        root = QVBoxLayout(self)
        root.setSpacing(C.SPACING["sm"])

        # 顶部概览卡：四个统计块
        overview = QFrame(self)
        theme.set_role(overview, "card")
        overview_layout = QHBoxLayout(overview)
        overview_layout.setContentsMargins(
            C.SPACING["lg"], C.SPACING["md"], C.SPACING["lg"], C.SPACING["md"]
        )
        overview_layout.setSpacing(C.SPACING["xl"])
        self._streak_block = _StatBlock(C.STATS_STREAK_LABEL, overview)
        self._mastered_block = _StatBlock(C.STATS_MASTERED_LABEL, overview)
        self._today_new_block = _StatBlock(C.STATS_TODAY_NEW_LABEL, overview)
        self._today_review_block = _StatBlock(C.STATS_TODAY_REVIEW_LABEL, overview)
        for block in (
            self._streak_block,
            self._mastered_block,
            self._today_new_block,
            self._today_review_block,
        ):
            overview_layout.addWidget(block)
        overview_layout.addStretch(1)
        root.addWidget(overview)

        self._empty_hint = QLabel(C.STATS_EMPTY_HINT, self)
        self._empty_hint.setStyleSheet(
            f"color: {C.SEMANTIC_COLORS['text_faint']};"
            f" font-size: {C.FONT_SIZE['caption']}px; background: transparent;"
        )
        self._empty_hint.setWordWrap(True)
        root.addWidget(self._empty_hint)

        # 中部：热力图卡片
        heat_card = QFrame(self)
        theme.set_role(heat_card, "card")
        heat_layout = QVBoxLayout(heat_card)
        heat_layout.setContentsMargins(
            C.SPACING["md"], C.SPACING["sm"], C.SPACING["md"], C.SPACING["sm"]
        )
        heat_layout.setSpacing(C.SPACING["xs"])
        heat_layout.addWidget(self._section_label(C.STATS_HEATMAP_TITLE))
        self._heatmap = _Heatmap(heat_card)
        heat_layout.addWidget(self._heatmap)
        root.addWidget(heat_card)

        # 中部：掌握曲线卡片
        curve_card = QFrame(self)
        theme.set_role(curve_card, "card")
        curve_layout = QVBoxLayout(curve_card)
        curve_layout.setContentsMargins(
            C.SPACING["md"], C.SPACING["sm"], C.SPACING["md"], C.SPACING["sm"]
        )
        curve_layout.setSpacing(C.SPACING["xs"])
        curve_layout.addWidget(self._section_label(C.STATS_CURVE_TITLE))
        self._curve = _Curve(curve_card)
        curve_layout.addWidget(self._curve)
        root.addWidget(curve_card, 1)

        # 底栏：关闭（与学习记录窗口底栏结构对齐）
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        self._btn_close = QPushButton(C.STATS_BTN_CLOSE, self)
        theme.set_variant(self._btn_close, "ghost")
        self._btn_close.setIcon(
            icon_factory.make_icon("close", color=C.SEMANTIC_COLORS["text_primary"])
        )
        self._btn_close.setIconSize(QSize(C.SPACING["lg"], C.SPACING["lg"]))
        self._btn_close.clicked.connect(self.close)
        bottom.addWidget(self._btn_close)
        root.addLayout(bottom)

    @staticmethod
    def _section_label(text: str) -> QLabel:
        """区块标题（加粗小标题，透明底）。"""

        label = QLabel(text)
        label.setStyleSheet(
            f"font-size: {C.FONT_SIZE['body']}px; font-weight: bold;"
            f" color: {C.SEMANTIC_COLORS['text_secondary']}; background: transparent;"
        )
        return label


__all__ = ["StatsWindow"]
