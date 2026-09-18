"""空闲游走 + 偶发换姿态回归测试（阶段 C1）。

对齐 design v1.1 §5.3-C 的四项硬验收 + G2 修正方案：

- 位移**严格有界**（含边界钳制）——`:func:`motion.wander_step`` 纯函数 + 窗口级长跑；
- **锚点不被游走改写**（G2 核心风险：重启后位置 = 锚点）；
- 拖拽即**重锚**（瞬态偏移归零、锚点 = 落点）；
- 多屏 ``clamp_to_screens`` 越屏保护生效；
- 游走 ``move()`` **不 emit** ``position_changed``（该信号只服务拖拽 → 持久化）；
- 游走 ``QTimer`` 挂 parent，且 ``closeEvent`` / ``stop_animation`` 会 ``stop()``；
- 换姿态：``SurpriseKind`` 新增 ``LOAF`` / ``LIE_SIDE``（``Expression`` 仍 == 8），
  使用 ``POSTURE_DURATION_S``，同样受 IDLE/REST 门控与 ``reduce_motion`` 抑制。

纪律：期望值一律写**字面量**（不引用被测常量自身拼期望）；每条新增断言均经变异验证。
"""

from __future__ import annotations

from dataclasses import fields

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QMouseEvent

from desktop_pet.core import constants as C
from desktop_pet.core import motion
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel, PetPose, SurpriseKind
from desktop_pet.ui.pet_renderer import PetRenderer
from desktop_pet.ui.pet_window import PetWindow


# --------------------------------------------------------------------------- #
# 测试辅助
# --------------------------------------------------------------------------- #
def _make_window(qtbot) -> PetWindow:
    """构造一个已显示的宠物窗口（offscreen）。"""

    window = PetWindow(PetModel(), PetRenderer(), 1.0)
    qtbot.addWidget(window)
    window.show()
    return window


def _mouse_event(
    etype,
    local_xy: tuple[float, float],
    global_xy: tuple[float, float],
    button: Qt.MouseButton = Qt.MouseButton.LeftButton,
    buttons: Qt.MouseButton = Qt.MouseButton.LeftButton,
) -> QMouseEvent:
    """构造一个合成的鼠标事件（local / global 均为像素坐标）。"""

    return QMouseEvent(
        etype,
        QPointF(float(local_xy[0]), float(local_xy[1])),
        QPointF(float(global_xy[0]), float(global_xy[1])),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def _drag(window: PetWindow, from_xy: tuple[int, int], delta: tuple[int, int]) -> None:
    """在 ``window`` 上模拟一次完整拖拽：按下 → 移动超阈值 → 释放。"""

    fx, fy = from_xy
    window.mousePressEvent(
        _mouse_event(QEvent.Type.MouseButtonPress, (0, 0), (fx, fy))
    )
    window.mouseMoveEvent(
        _mouse_event(QEvent.Type.MouseMove, (delta[0], delta[1]),
                     (fx + delta[0], fy + delta[1]))
    )
    window.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.MouseButtonRelease,
            (delta[0], delta[1]),
            (fx + delta[0], fy + delta[1]),
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.NoButton,
        )
    )


# --------------------------------------------------------------------------- #
# 1. 常量字面量 + __all__ 登记
# --------------------------------------------------------------------------- #
def test_wander_constants_literal_values() -> None:
    assert C.WANDER_MAX_PX == 20.0
    assert C.WANDER_STEP_PX == 6.0
    assert C.WANDER_TICK_MS == 3000
    assert C.POSTURE_DURATION_S == 6.0
    assert C.SURPRISE_POSTURE_KINDS == frozenset({"LOAF", "LIE_SIDE"})


def test_wander_constants_registered_in_all() -> None:
    for name in (
        "WANDER_MAX_PX", "WANDER_STEP_PX", "WANDER_TICK_MS",
        "POSTURE_DURATION_S", "SURPRISE_POSTURE_KINDS",
    ):
        assert name in C.__all__, f"{name} 未登记进 constants.__all__"


def test_wander_step_registered_in_motion_all() -> None:
    assert "wander_step" in motion.__all__


# --------------------------------------------------------------------------- #
# 2. 位移严格有界 + 边界钳制（纯函数）
# --------------------------------------------------------------------------- #
def test_wander_step_clamps_on_both_axes() -> None:
    assert motion.wander_step(19.0, -19.0, 5.0, -5.0, 20.0) == (20.0, -20.0)
    assert motion.wander_step(-19.0, 19.0, -5.0, 5.0, 20.0) == (-20.0, 20.0)


def test_wander_step_pinned_at_boundary() -> None:
    """偏移已在边界时继续同向外推 → 钳在原地、不再外扩（有界性核心）。"""

    assert motion.wander_step(20.0, 20.0, 6.0, 6.0, 20.0) == (20.0, 20.0)
    assert motion.wander_step(-20.0, -20.0, -6.0, -6.0, 20.0) == (-20.0, -20.0)


def test_wander_step_zero_or_negative_max_pins_origin() -> None:
    assert motion.wander_step(5.0, -5.0, 3.0, 3.0, 0.0) == (0.0, 0.0)
    assert motion.wander_step(5.0, -5.0, 3.0, 3.0, -1.0) == (0.0, 0.0)


def test_wander_step_within_bound_is_exact_sum() -> None:
    assert motion.wander_step(0.0, 0.0, 3.0, -4.0, 20.0) == (3.0, -4.0)


# --------------------------------------------------------------------------- #
# 3. 窗口级：位移始终有界；锚点不被游走改写（G2）
# --------------------------------------------------------------------------- #
def test_wander_keeps_offset_within_literal_bound(qtbot) -> None:
    window = _make_window(qtbot)
    window.set_anchor(300, 250)
    # 从一个已贴近边界的状态出发
    window._wander_offset_x = 20.0
    window._wander_offset_y = -20.0
    ran = False
    for _ in range(40):
        window._on_wander_tick()
        ox, oy = window.wander_offset()
        assert -20.0 <= ox <= 20.0
        assert -20.0 <= oy <= 20.0
        if (ox, oy) != (20.0, -20.0):
            ran = True
    assert ran, "游走未实际执行（可见性门控误挡？）"


def test_wander_does_not_mutate_anchor(qtbot) -> None:
    """**G2 核心**：游走只动瞬态偏移，锚点保持不变。"""

    window = _make_window(qtbot)
    window.set_anchor(300, 250)
    for _ in range(60):
        window._on_wander_tick()
    assert window.anchor() == (300, 250)


def test_wander_move_does_not_emit_position_changed(qtbot) -> None:
    window = _make_window(qtbot)
    window.set_anchor(300, 250)
    received: list[tuple[int, int]] = []
    window.position_changed.connect(lambda x, y: received.append((x, y)))
    positions: set[tuple[int, int]] = set()
    for _ in range(80):
        window._on_wander_tick()
        positions.add((window.x(), window.y()))
    assert len(positions) > 1, "游走未实际移动窗口（门控误挡？）"
    assert received == [], f"游走不应 emit position_changed：{received}"


def test_wander_paused_while_dragging(qtbot) -> None:
    window = _make_window(qtbot)
    window.set_anchor(300, 250)
    _drag(window, (300, 250), (40, 0))
    # 拖拽进行中（未释放前）
    window.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, (0, 0), (340, 250)))
    window.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (40, 0), (380, 250)))
    assert window._dragging
    before = window.pos()
    for _ in range(20):
        window._on_wander_tick()
    assert window.pos() == before, "拖拽中不应游走"


def test_persist_saves_anchor_not_window_pos(qtbot, tmp_path) -> None:
    """**G2 持久化契约**：Controller 落盘的是**锚点**，不是窗口 ``pos()``。

    这样即便游走把窗口挪到锚点 + 偏移处，退出 / 拖拽结束保存的仍是不含瞬态偏移的锚点
    —— 否则随机位置会被存成新锚点、跨会话持续漂移（v1.1 §2.3 G2 / 风险 6）。
    """

    from PySide6.QtWidgets import QApplication

    from desktop_pet.app.controller import PetAppController
    from desktop_pet.core.config import AppConfig, ConfigStore

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(AppConfig(listen_enabled=False))
    app = QApplication.instance()
    assert isinstance(app, QApplication)

    controller = PetAppController(app, store)
    try:
        # 锚点 = (300, 250)，但施加瞬态偏移后窗口实际位置 ≠ 锚点
        controller._window.set_anchor(300, 250)
        controller._window._wander_offset_x = 15.0
        controller._window._wander_offset_y = 10.0
        controller._window._apply_wander_position()
        assert (controller._window.x(), controller._window.y()) != (300, 250)

        controller._persist()
        cfg = store.load()
        assert (cfg.window_x, cfg.window_y) == (300, 250)
    finally:
        controller.shutdown()


# --------------------------------------------------------------------------- #
# 4. 拖拽即重锚（offset 归零、锚点 = 落点）
# --------------------------------------------------------------------------- #
def test_drag_start_reanchors_and_zeroes_offset(qtbot) -> None:
    window = _make_window(qtbot)
    window.set_anchor(200, 200)
    # 制造非零瞬态偏移，并同步窗口位置（模拟「游走之后」）
    window._wander_offset_x = 12.0
    window._wander_offset_y = -7.0
    window.move(212, 193)

    window.mousePressEvent(_mouse_event(QEvent.Type.MouseButtonPress, (0, 0), (212, 193)))
    window.mouseMoveEvent(_mouse_event(QEvent.Type.MouseMove, (60, 0), (272, 193)))

    assert window.anchor() == (212, 193), "拖拽开始应重锚到当前实际位置"
    assert window.wander_offset() == (0.0, 0.0), "拖拽开始应清零瞬态偏移"

    window.mouseReleaseEvent(
        _mouse_event(
            QEvent.Type.MouseButtonRelease, (60, 0), (272, 193),
            button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.NoButton,
        )
    )


# --------------------------------------------------------------------------- #
# 5. 越屏保护：多屏 clamp_to_screens（含 wander 落位路径）
# --------------------------------------------------------------------------- #
def test_clamp_to_screens_handles_two_screen_layout() -> None:
    screens = [(0, 0, 1920, 1080), (1920, 0, 1920, 1080)]
    # 完整落在第二屏内 → 原样
    assert motion.clamp_to_screens(2000, 100, 160, 180, screens) == (2000, 100)
    # 越过第二屏右缘 → 钳回第二屏可见区
    assert motion.clamp_to_screens(3800, 100, 160, 180, screens) == (3680, 100)
    # 完全越界（不与任何屏相交）→ 回落主屏右下内缩（1920-160-40, 1080-180-40）
    assert motion.clamp_to_screens(-99999, -99999, 160, 180, screens) == (1720, 860)


def test_wander_position_is_clamped_to_visible_screen(qtbot) -> None:
    window = _make_window(qtbot)
    px, py, pw, ph = window._primary_geometry()
    max_x = px + pw - window.width()
    max_y = py + ph - window.height()
    window.set_anchor(max_x, max_y)
    # 偏移钉在 +max（向右下外推）→ 若不经 clamp 必定越界
    window._wander_offset_x = 20.0
    window._wander_offset_y = 20.0
    window._apply_wander_position()
    gx, gy = window.x(), window.y()
    assert px <= gx <= max_x
    assert py <= gy <= max_y


# --------------------------------------------------------------------------- #
# 6. 游走 QTimer：挂 parent + 生命周期 stop（closeEvent / stop_animation）
# --------------------------------------------------------------------------- #
def test_wander_timer_is_parented_to_window(qtbot) -> None:
    window = _make_window(qtbot)
    assert window._wander_timer.parent() is window
    assert window._wander_timer.interval() == 3000


def test_start_animation_starts_wander_timer(qtbot) -> None:
    window = _make_window(qtbot)
    window.stop_animation()
    assert not window._wander_timer.isActive()
    window.start_animation()
    assert window._wander_timer.isActive()


def test_stop_animation_stops_wander_timer(qtbot) -> None:
    window = _make_window(qtbot)
    window.start_animation()
    assert window._wander_timer.isActive()
    window.stop_animation()
    assert not window._wander_timer.isActive()


def test_close_event_stops_wander_timer(qtbot) -> None:
    window = _make_window(qtbot)
    window.start_animation()
    assert window._wander_timer.isActive()
    window.close()
    assert not window._wander_timer.isActive()


# --------------------------------------------------------------------------- #
# 7. 偶发换姿态（LOAF / LIE_SIDE）
# --------------------------------------------------------------------------- #
def test_posture_kinds_are_surprise_members_not_expressions() -> None:
    names = {k.name for k in SurpriseKind}
    assert {"LOAF", "LIE_SIDE"} <= names
    assert len(list(Expression)) == 8, "不得新增 Expression 成员"


def test_posture_poses_use_only_existing_channels() -> None:
    valid = {f.name for f in fields(PetPose)}
    for name in ("LOAF", "LIE_SIDE"):
        deltas = C.SURPRISE_POSES[name]
        assert deltas, f"{name} 增量为空"
        assert set(deltas) <= valid, f"{name} 使用了不存在的通道：{set(deltas) - valid}"


def test_posture_duration_longer_than_small_action() -> None:
    assert PetModel._surprise_duration(SurpriseKind.LOAF) == 6.0
    assert PetModel._surprise_duration(SurpriseKind.LIE_SIDE) == 6.0
    assert PetModel._surprise_duration(SurpriseKind.STRETCH) == 1.2


def test_posture_applies_pose_delta_then_expires() -> None:
    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)
    base = PetModel.pose_for_expression(Expression.HAPPY)

    # 字面量锁定 LOAF 的 body_y 增量
    assert C.SURPRISE_POSES["LOAF"]["body_y"] == 6.0

    # 保持段（包络 = 1.0）：LOAF 的 body_y 增量应完整叠加（重心下压 = 正位移）
    model._surprise_kind = SurpriseKind.LOAF
    model._surprise_elapsed = C.POSTURE_DURATION_S * 0.45
    posed = PetModel.pose_for_expression(Expression.HAPPY)
    model._apply_actions(posed)
    assert posed.body_y == pytest.approx(base.body_y + 6.0)
    assert posed.body_y > base.body_y

    # 无进行中的姿态 ⇒ 通道归位
    model._surprise_kind = None
    resting = PetModel.pose_for_expression(Expression.HAPPY)
    model._apply_actions(resting)
    assert resting.body_y == pytest.approx(base.body_y)


def test_posture_can_be_scheduled_and_is_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    """换姿态可被调度；拖拽门控触发时立即取消（复用 A5 同一门控）。"""

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)
    monkeypatch.setattr(model, "_pick_surprise", lambda: SurpriseKind.LIE_SIDE)

    model._calm_seconds = C.REST_THRESHOLD_S
    model._surprise_timer = 0.0
    model.update(0.033, 1.0)
    assert model._surprise_kind is SurpriseKind.LIE_SIDE

    model.set_dragging(True)
    model.update(0.033, 1.033)
    assert model._surprise_kind is None, "门控失效应立即取消进行中的换姿态"


def test_posture_suppressed_when_reduce_motion(monkeypatch: pytest.MonkeyPatch) -> None:
    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)
    model.set_reduce_motion(True)
    monkeypatch.setattr(model, "_pick_surprise", lambda: SurpriseKind.LOAF)

    model._calm_seconds = C.REST_THRESHOLD_S
    model._surprise_timer = 0.0
    model.update(0.033, 1.0)
    assert model._surprise_kind is None
