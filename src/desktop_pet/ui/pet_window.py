"""ui.pet_window —— 无边框透明置顶宠物窗口 + 鼠标手势 + 帧循环。

窗口标志：``FramelessWindowHint | WindowStaysOnTopHint | Qt.Tool``
+ ``WA_TranslucentBackground``（FR-15/16/17）。

手势区分（架构 §1.3）：
- 位移 < ``DRAG_THRESHOLD_PX``(5) 且松手 → 判定为**点击**（FR-27）。
- 位移 >= 阈值 → 判定为**拖拽**，窗口跟手移动并在松手后发出 ``drag_finished``（FR-18）。
- 悬停 >= ``HOVER_TRIGGER_S``(1) → 发出 HOVER 手势（FR-28）。

帧率：``set_fps`` 动态切换 30/15/8 FPS；常态用 ``update(pet_rect)`` 脏区刷新（FR-34/35）。
"""

from __future__ import annotations

import logging
import random
import time
import warnings

from PySide6.QtCore import QPoint, QRect, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QCloseEvent,
    QContextMenuEvent,
    QCursor,
    QGuiApplication,
    QMouseEvent,
    QPaintEvent,
    QPainter,
)
from PySide6.QtWidgets import QMenu, QWidget

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.constants import Gesture
from desktop_pet.core.pet_model import PetModel
from desktop_pet.ui.pet_renderer import PetRenderer

logger = logging.getLogger(__name__)


class PetWindow(QWidget):
    """宠物主窗口（无边框 / 透明 / 置顶 / 不占任务栏）。"""

    #: 窗口位置变化：(x, y)
    position_changed = Signal(int, int)
    #: 触发鼠标手势：``Gesture`` 的整数值
    gesture_triggered = Signal(int)
    #: 拖拽结束：(final_x, final_y)
    drag_finished = Signal(int, int)
    #: 帧循环节拍：携带当前时刻（秒）。供 Controller 驱动状态机/模型推进
    frame_tick = Signal(float)

    def __init__(self, model: PetModel, renderer: PetRenderer, scale: float) -> None:
        """构造宠物窗口。

        Args:
            model: 姿态模型。
            renderer: 矢量渲染器。
            scale: 初始缩放档（0.8 / 1.0 / 1.2）。
        """

        super().__init__()
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setWindowTitle(C.APP_DISPLAY_NAME)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._model: PetModel = model
        self._renderer: PetRenderer = renderer
        self._scale: float = float(scale)
        self._fps: int = C.FPS_IDLE

        # 拖拽 / 点击判定
        self._drag_origin: QPoint = QPoint(0, 0)   # 按下时的窗口左上角
        self._press_pos: QPoint = QPoint(0, 0)     # 按下时的全局鼠标坐标
        self._dragging: bool = False

        # 悬停抚摸
        self._hover_timer = QTimer(self)
        self._hover_timer.setSingleShot(True)
        self._hover_timer.setInterval(int(C.HOVER_TRIGGER_S * 1000))
        self._hover_timer.timeout.connect(self._on_hover_triggered)
        self._hover_active: bool = False

        # 锚点式空闲游走（阶段 C1-1）
        #   锚点 = 稳定基准（= 持久化写入对象）；offset = **严格有界**的瞬态偏移。
        #   游走位置 = 锚点 + offset，且 **绝不** emit position_changed —— 该信号只服务
        #   「用户拖拽 → 持久化」；若游走也发它，随机位置会被存成新锚点、跨会话持续漂移
        #   （v1.1 §2.3 G2 / 风险 6）。
        self._wander_anchor: QPoint = QPoint(0, 0)
        self._wander_offset_x: float = 0.0
        self._wander_offset_y: float = 0.0
        self._wander_timer = QTimer(self)
        self._wander_timer.setInterval(C.WANDER_TICK_MS)
        self._wander_timer.timeout.connect(self._on_wander_tick)

        # 右键菜单（由 Controller 注入复用托盘菜单）
        self._context_menu: QMenu | None = None

        # 帧循环
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._on_frame)

        self._apply_size()

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def set_scale(self, scale: float) -> None:
        """设置缩放档并立即生效（FR-20）。"""

        self._scale = float(scale)
        self._apply_size()
        self.update()

    def set_fps(self, fps: int) -> None:
        """设置帧率（动态切换定时器间隔，FR-34）。"""

        fps = max(1, int(fps))
        if fps == self._fps and self._timer.isActive():
            return
        self._fps = fps
        self._timer.setInterval(C.interval_for_fps(fps))

    def start_animation(self) -> None:
        """启动帧循环与空闲游走。"""

        if not self._timer.isActive():
            self._timer.start(C.interval_for_fps(self._fps))
        self.start_wander()

    def stop_animation(self) -> None:
        """停止帧循环与空闲游走（避免残留定时器 / 事件，FR-24）。"""

        self._timer.stop()
        self.stop_wander()

    def restore_position(self, x: int, y: int) -> None:
        """恢复到指定位置（重启恢复，FR-36），同时把它设为新的游走锚点（offset 归零）。"""

        self.set_anchor(x, y)

    def set_anchor(self, x: int, y: int) -> None:
        """把 ``(x, y)`` 设为游走锚点、复位瞬态偏移，并把窗口移到锚点。

        锚点是**稳定基准**：空闲游走只在锚点邻域 ``±WANDER_MAX_PX`` 内浮动，
        **永不改写锚点本身** → 重启后位置回到锚点、不随随机游走漂移（G2 修正方案）。
        拖拽结束（Controller 越界钳制后）与从托盘恢复也都经此重置基准。
        """

        self._wander_anchor = QPoint(int(x), int(y))
        self._wander_offset_x = 0.0
        self._wander_offset_y = 0.0
        self.move(int(x), int(y))

    def anchor(self) -> tuple[int, int]:
        """返回当前游走锚点（= 持久化基准，**不含**瞬态偏移）。"""

        return self._wander_anchor.x(), self._wander_anchor.y()

    def wander_offset(self) -> tuple[float, float]:
        """返回当前瞬态游走偏移 ``(offset_x, offset_y)``（供测试 / 调试观察）。"""

        return self._wander_offset_x, self._wander_offset_y

    def start_wander(self) -> None:
        """启动空闲游走定时器（幂等）。"""

        if not self._wander_timer.isActive():
            self._wander_timer.start(C.WANDER_TICK_MS)

    def stop_wander(self) -> None:
        """停止空闲游走定时器（幂等）。"""

        self._wander_timer.stop()

    def set_context_menu(self, menu: QMenu) -> None:
        """注入右键菜单（由 Controller 复用托盘菜单实例）。"""

        self._context_menu = menu

    def current_scale(self) -> float:
        """返回当前缩放档。"""

        return self._scale

    def pet_rect(self) -> QRect:
        """返回宠物脏区包围矩形（窗口坐标，用于局部刷新，FR-35）。

        收窄策略（FR-35 / 架构 §6.2）：

        * **常态**：返回 :meth:`PetRenderer.body_bounds` 计算的**猫咪本体**最小
          包围矩形（已按当前缩放映射到窗口像素、并钳制在窗口内）。每帧只重绘
          猫身附近区域，而非整窗。
        * **回退整窗**：睡觉（SLEEPING）与兴奋（EXCITED）两种表情会绘制
          **铺满整窗**的径向光晕（此时 ``pose.glow_alpha > GLOW_ALPHA_EPSILON``）。
          收窄矩形会把光晕边缘裁掉，所以这两种状态下必须回退为整窗矩形。
        """

        pose = self._model.pose()
        # 光晕铺满整窗的状态（睡觉 / 兴奋）无法收窄 → 回退整窗矩形，避免裁掉光晕。
        if pose.glow_alpha > PetRenderer.GLOW_ALPHA_EPSILON:
            return self.rect()
        bounds = PetRenderer.body_bounds(pose, self._scale)
        # 与窗口求交，确保任何情况下都落在窗口内（防御缩放假值/边界误差）。
        return bounds.intersected(self.rect())

    def refresh(self) -> None:
        """请求脏区重绘（FR-35：用 ``update(rect)`` 而非整窗 ``update()``）。"""

        self.update(self.pet_rect())

    # ------------------------------------------------------------------ #
    # 绘制
    # ------------------------------------------------------------------ #
    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        """绘制一帧矢量猫咪。"""

        painter = QPainter(self)
        try:
            self._renderer.paint(painter, self._model.pose(), self._scale, self.size())
        finally:
            painter.end()

    # ------------------------------------------------------------------ #
    # 鼠标事件
    # ------------------------------------------------------------------ #
    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """按下：记录拖拽原点（左键）。"""

        if event.button() == Qt.MouseButton.LeftButton:
            self._press_pos = event.globalPosition().toPoint()
            self._drag_origin = self.pos()
            self._dragging = False
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """移动：超过阈值才判定为拖拽并跟手移动窗口。"""

        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        current = event.globalPosition().toPoint()
        delta = current - self._press_pos
        if not self._dragging and (delta.manhattanLength()) >= C.DRAG_THRESHOLD_PX:
            self._dragging = True
            # 拖拽开始：把当前实际位置吸收为新锚点、瞬态偏移归零（G2 修正方案）。
            # 必须在跟手移动**之前**做：先让锚点追上窗口现位置，再清零 offset，
            # 否则归零会把窗口瞬间拉回旧锚点。
            self._absorb_wander_offset()
            self._model.set_dragging(True)
        if self._dragging:
            new_pos = self._drag_origin + delta
            self.move(new_pos)
            self.position_changed.emit(new_pos.x(), new_pos.y())

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        """松开：区分点击与拖拽结束。"""

        if event.button() != Qt.MouseButton.LeftButton:
            event.accept()
            return
        if self._dragging:
            self._dragging = False
            self._model.set_dragging(False)
            self.drag_finished.emit(self.x(), self.y())
        else:
            # 位移小于阈值 → 点击
            self.gesture_triggered.emit(int(Gesture.CLICK))
        event.accept()

    def enterEvent(self, event) -> None:  # noqa: N802
        """进入：启动悬停抚摸计时（FR-28）。

        **可见性守卫**（teardown 崩溃根因修复之一）：窗口 ``show()`` 时若光标
        恰好落在窗内，Qt 会**异步**投递一个 enter 事件；若该事件在窗口 ``close()``
        之后才被事件循环派发，无守卫的 ``_hover_timer.start()`` 会在**已关闭**的
        窗口上重新启动悬停定时器 —— 留下活表，在 pytest-qt teardown 的
        ``processEvents()`` 窗口内触发原生 abort（QA 阻断项机制）。
        对不可见窗口的 enter 事件是伪事件，直接吞掉。
        """

        if not self.isVisible():
            event.accept()
            return
        self._hover_timer.start()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        """离开：取消悬停抚摸。"""

        self._hover_timer.stop()
        if self._hover_active:
            self._hover_active = False
            self._model.set_hover(False)
        super().leaveEvent(event)

    def contextMenuEvent(self, event: QContextMenuEvent) -> None:  # noqa: N802
        """右键：弹出注入的菜单（FR-19）。"""

        if self._context_menu is not None:
            self._context_menu.popup(event.globalPos())
        event.accept()

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        """关闭：停止帧循环与空闲游走定时器，并**显式断开** timeout 连接（FR-24）。

        显式 ``disconnect()`` 是 QA 阻断项（teardown 原生 abort）的源侧加固之一：
        停表只保证不再产生**新**事件，断开连接才能保证已入队的事件派发时槽函数
        不会被调用（回调进入正在析构的 C++ 对象 → ``Fatal Python error: Aborted``，
        Python 层 ``try/except`` 无法拦截）。
        """

        for t in (self._timer, self._wander_timer, self._hover_timer):
            t.stop()
        # 显式断开（按绑定方法）。PySide6 下对未连接信号断开**不抛异常**、只发
        # RuntimeWarning —— 而「未连接」本就是目标状态，故就地压掉该警告。
        # （try/except 保留作版本兼容：旧版 PySide6 会抛 RuntimeError。）
        for t, slot in (
            (self._timer, self._on_frame),
            (self._wander_timer, self._on_wander_tick),
        ):
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore", RuntimeWarning)
                    t.timeout.disconnect(slot)
            except (RuntimeError, TypeError):
                pass  # 已断开 / 从未连接 → 目标状态一致
        super().closeEvent(event)

    def has_active_timers(self) -> bool:
        """是否存在仍活跃的窗口级定时器（只读探针）。

        供测试侧 conftest 的**确定性不变量守卫**使用：任何用例结束时都必须为
        False，否则该窗口在 pytest-qt teardown 的 ``processEvents()`` 窗口内
        有触发原生 abort 的风险（见 :meth:`closeEvent` 说明）。
        """

        return (
            self._timer.isActive()
            or self._wander_timer.isActive()
            or self._hover_timer.isActive()
        )

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _apply_size(self) -> None:
        """按缩放档调整窗口尺寸（宠物包围盒每帧由 :meth:`pet_rect` 现算）。"""

        width = int(round(C.BASE_W * self._scale))
        height = int(round(C.BASE_H * self._scale))
        self.setFixedSize(QSize(width, height))

    def _absorb_wander_offset(self) -> None:
        """把当前瞬态偏移吸收进锚点并清零 offset（拖拽开始时调用，G2）。

        先令锚点 = 窗口**现位置**（= 旧锚点 + 现偏移），再把 offset 归零：二者代数和
        不变 → 窗口不跳；此后游走相对新锚点展开。
        """

        self._wander_anchor = self.pos()
        self._wander_offset_x = 0.0
        self._wander_offset_y = 0.0

    def _on_wander_tick(self) -> None:
        """一次空闲游走节拍：随机迈一步（offset 严格有界）后落位。

        门控：拖拽 / 悬停 / 不可见期间不游走（避免与用户操作打架）；
        **空闲时长未达 ``REST_THRESHOLD_S`` 也不游走** —— 复用
        :attr:`PetModel.calm_seconds`（与偶发小动作**同一**空闲定义，v1.1 §G3）。
        空闲门控是「位置漂移」缺陷的根因修复点：``start_wander()`` 随
        ``start_animation()`` 在应用启动即开表，若只判拖拽/悬停，宠物会在用户
        正常使用期间每 ``WANDER_TICK_MS`` 随机走一步并**永不回到锚点**，
        表现为持续位置漂移。
        """

        try:
            if self._dragging or self._hover_active or not self.isVisible():
                return
            if not self._model.is_quiet_for_wander():
                return
            dx = random.uniform(-C.WANDER_STEP_PX, C.WANDER_STEP_PX)
            dy = random.uniform(-C.WANDER_STEP_PX, C.WANDER_STEP_PX)
            # 步进结果严格钳制在 ±WANDER_MAX_PX：偏移到达边界后不再继续外推（G2）。
            self._wander_offset_x, self._wander_offset_y = motion.wander_step(
                self._wander_offset_x, self._wander_offset_y, dx, dy, C.WANDER_MAX_PX
            )
            self._apply_wander_position()
        except Exception:  # noqa: BLE001 —— 游走失败不影响动画
            logger.debug("空闲游走采样失败（已忽略）", exc_info=True)

    def _apply_wander_position(self) -> None:
        """把「锚点 + 瞬态偏移」落到窗口位置，并经 :func:`motion.clamp_to_screens` 钳制。

        硬约束：本方法**绝不** emit ``position_changed`` —— 该信号只服务用户拖拽 →
        持久化；游走位置是瞬态的，不得污染锚点（v1.1 §2.3 G2 / 风险 6）。
        """

        target_x = self._wander_anchor.x() + int(round(self._wander_offset_x))
        target_y = self._wander_anchor.y() + int(round(self._wander_offset_y))
        cx, cy = motion.clamp_to_screens(
            target_x,
            target_y,
            self.width(),
            self.height(),
            self._screen_geometries(),
            self._primary_geometry(),
        )
        self.move(cx, cy)

    @staticmethod
    def _screen_geometries() -> list[tuple[int, int, int, int]]:
        """返回全部屏幕的几何列表（游走越屏钳制用）。"""

        result: list[tuple[int, int, int, int]] = []
        try:
            for screen in QGuiApplication.screens():
                rect = screen.geometry()
                result.append((rect.x(), rect.y(), rect.width(), rect.height()))
        except Exception:  # noqa: BLE001
            logger.debug("获取屏幕列表失败（已忽略）", exc_info=True)
        return result

    @staticmethod
    def _primary_geometry() -> tuple[int, int, int, int]:
        """返回主屏几何（不可用时回落 1920×1080 虚拟主屏）。"""

        try:
            screen = QGuiApplication.primaryScreen()
            if screen is not None:
                rect = screen.geometry()
                return (rect.x(), rect.y(), rect.width(), rect.height())
        except Exception:  # noqa: BLE001
            logger.debug("获取主屏几何失败（已忽略）", exc_info=True)
        return (0, 0, 1920, 1080)

    def _on_hover_triggered(self) -> None:
        """悬停达到阈值 → 抚摸反应。"""

        self._hover_active = True
        self._model.set_hover(True)
        self.gesture_triggered.emit(int(Gesture.HOVER))

    def _update_tail_evade(self) -> None:
        """按**全局光标**与尾巴中心线的亲近度，写入尾巴避让目标（FR-13 扩展）。

        职责边界：

        * 尾巴几何（脊线）来自 :meth:`PetRenderer.tail_spine` —— 与绘制共用同一条线；
        * 距离→强度的映射与侧别判定在 :mod:`desktop_pet.core.motion`（纯计算、可单测）；
        * 本方法只做「全局屏幕坐标 → 逻辑画布坐标」的换算与调用。

        任何异常都只记 debug 日志：交互采样绝不能拖垮帧循环。
        """

        try:
            if not self.isVisible():
                self._model.set_tail_evade(0.0, 0.0, 0.0)
                return

            scale = self._scale if self._scale else 1.0
            local = self.mapFromGlobal(QCursor.pos())
            px = local.x() / scale
            py = local.y() / scale

            # 基准必须是"无避让"的脊线：含位移的姿态会让 位移→距离变大→强度变小→
            # 位移收回→距离又变小 形成自激回路，尾巴在临界距离上持续抖动。
            spine = PetRenderer.tail_spine(self._model.pose(), apply_flee=False)
            distance, _side = motion.polyline_proximity(px, py, spine)
            amount = motion.tail_evade_amount(
                distance, C.TAIL_EVADE_NEAR_PX, C.TAIL_EVADE_FAR_PX
            )
            dir_x, dir_y = motion.flee_direction(
                px, py, spine, lift=C.TAIL_EVADE_LIFT
            )
            self._model.set_tail_evade(amount, dir_x, dir_y)
        except Exception:  # noqa: BLE001 —— 交互采样失败不影响动画
            logger.debug("尾巴亲近度采样失败（已忽略）", exc_info=True)

    def _update_gaze(self) -> None:
        """悬停激活期间按光标方向写入注视向量（阶段 B2-1，P5）。

        职责边界与 :meth:`_update_tail_evade` 一致：本方法只做「全局屏幕坐标 →
        逻辑画布坐标」的换算与调用；方向归一化在
        :func:`desktop_pet.core.motion.gaze_vector`（纯计算、可单测）。

        基准点取 :meth:`PetRenderer.face_center`（脸部中心，与绘制共用同一基准）。
        非悬停态写入 ``(0, 0)``，保证离开悬停后瞳孔平滑回到正前方。任何异常都
        只记 debug 日志：交互采样绝不能拖垮帧循环。
        """

        try:
            if not self._hover_active or not self.isVisible():
                self._model.clear_gaze()
                return

            scale = self._scale if self._scale else 1.0
            local = self.mapFromGlobal(QCursor.pos())
            px = local.x() / scale
            py = local.y() / scale
            cx, cy = PetRenderer.face_center(self._model.pose())
            nx, ny = motion.gaze_vector(px, py, cx, cy, C.HOVER_GAZE_MAX_DIST_PX)
            self._model.set_gaze(nx, ny)
        except Exception:  # noqa: BLE001 —— 交互采样失败不影响动画
            logger.debug("悬停注视采样失败（已忽略）", exc_info=True)

    def _on_frame(self) -> None:
        """定时器节拍：采样光标 → 更新尾巴避让 / 悬停注视 → 向 Controller 发出帧信号。

        前置**可见性守卫**（QA 阻断项加固）：不可见时直接返回 —— 隐藏窗口的
        定时器节拍不再触碰渲染状态，避免窗口析构竞态下回调进入已失效对象。
        """

        if not self.isVisible():
            return
        self._update_tail_evade()
        self._update_gaze()
        self.frame_tick.emit(time.monotonic())


__all__ = ["PetWindow"]
