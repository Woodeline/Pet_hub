"""ui.motion_ui —— 动效（淡入 / 淡出 / 标签透明度）的**唯一判定与构造入口**。

职责边界：
- 本模块负责把「是否播放动效」与「如何构造动画对象」集中到一处；**几何计算、绘制、
  窗口业务逻辑一律不在此处**（那些属于各自的窗口 / 渲染器）。
- 「减少动效」（``prefers-reduced-motion`` 对应项）统一由 :func:`motion_enabled` 判定：
  ``reduce_motion=True`` → 关闭动效，**直接跳到终态且不创建任何动画对象**。
- 所有 ``QPropertyAnimation`` 均以目标对象为 ``parent``，随窗口一同销毁，避免泄漏。

设计约束（对应计划 §4）：
- 动效**不依赖真实窗口显示**：offscreen 平台下可实例化、可 ``start()``、可 ``stop()``。
- 淡入 = 透明度 0→1 **且**位置上移 ``MOTION_RISE_PX`` 落位（浅入 + 微位移，克制原则）。
- 淡出时长更短（``MOTION_FADE_OUT_MS``），完成后回调 ``on_finished``。
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from PySide6.QtCore import QPoint, QPropertyAnimation
from PySide6.QtWidgets import QGraphicsOpacityEffect, QWidget

#: 窗口淡入时长（ms）。
MOTION_FADE_IN_MS: Final[int] = 200
#: 窗口淡出时长（ms，比淡入更短，收尾干脆）。
MOTION_FADE_OUT_MS: Final[int] = 150
#: 淡入时的上移距离（px）：从 ``y + MOTION_RISE_PX`` 落位到 ``y``。
MOTION_RISE_PX: Final[int] = 4
#: 状态标签淡入时长（ms）。
MOTION_LABEL_FADE_MS: Final[int] = 200


def motion_enabled(reduce_motion: bool | None = None) -> bool:
    """统一判定是否播放动效。

    Args:
        reduce_motion: 「减少动效」开关；``True`` → 关闭动效；``False`` / ``None`` → 开启。

    Returns:
        是否应播放动效。
    """

    return reduce_motion is not True


class WindowMotion:
    """窗口级动效控制器（淡入 / 淡出）。

    Attributes:
        window: 被操控的目标窗口。
        reduce_motion: 是否处于「减少动效」态（``True`` 表示关闭动效）。
        opacity_animation: 透明度动画（关闭动效时为 ``None``）。
        pos_animation: 位移动画（关闭动效时为 ``None``）。
    """

    def __init__(self, window: QWidget, reduce_motion: bool | None = None) -> None:
        """构造窗口动效控制器（此时**不**创建任何动画对象）。"""

        self.window: QWidget = window
        self.reduce_motion: bool = bool(reduce_motion)
        self._enabled: bool = motion_enabled(reduce_motion)
        self.opacity_animation: QPropertyAnimation | None = None
        self.pos_animation: QPropertyAnimation | None = None

    def fade_in(self) -> None:
        """淡入：透明度 0→1 且位置由 ``y+MOTION_RISE_PX`` 上移落位。

        关闭动效时**直接终态**（透明度置 1、位置不动），且不创建动画对象。
        """

        if not self._enabled:
            self.window.setWindowOpacity(1.0)
            return

        target = self.window.pos()
        start_pos = QPoint(target.x(), target.y() + MOTION_RISE_PX)
        self.window.move(start_pos)
        self.window.setWindowOpacity(0.0)

        self.opacity_animation = QPropertyAnimation(
            self.window, b"windowOpacity", self.window
        )
        self.opacity_animation.setDuration(MOTION_FADE_IN_MS)
        self.opacity_animation.setStartValue(0.0)
        self.opacity_animation.setEndValue(1.0)

        self.pos_animation = QPropertyAnimation(self.window, b"pos", self.window)
        self.pos_animation.setDuration(MOTION_FADE_IN_MS)
        self.pos_animation.setStartValue(start_pos)
        self.pos_animation.setEndValue(target)

        self.opacity_animation.start()
        self.pos_animation.start()

    def fade_out(self, on_finished: Callable[[], None] | None = None) -> None:
        """淡出：透明度 1→0，完成后调用 ``on_finished``（若有）。

        关闭动效时**直接**同步调用 ``on_finished``，不创建动画对象。
        """

        if not self._enabled:
            if on_finished is not None:
                on_finished()
            return

        self.opacity_animation = QPropertyAnimation(
            self.window, b"windowOpacity", self.window
        )
        self.opacity_animation.setDuration(MOTION_FADE_OUT_MS)
        self.opacity_animation.setStartValue(1.0)
        self.opacity_animation.setEndValue(0.0)
        if on_finished is not None:
            self.opacity_animation.finished.connect(on_finished)
        self.opacity_animation.start()


def create_window_motion(
    window: QWidget, reduce_motion: bool | None = None
) -> WindowMotion:
    """为 ``window`` 创建（尚不启动的）窗口动效控制器。"""

    return WindowMotion(window, reduce_motion)


def show_window_animated(
    window: QWidget, reduce_motion: bool | None = None
) -> WindowMotion:
    """显示窗口并播放淡入动效，返回动效控制器（供调用方持有 / 后续停止）。"""

    window.show()
    motion = create_window_motion(window, reduce_motion)
    motion.fade_in()
    return motion


def fade_label_in(
    label: QWidget, reduce_motion: bool | None = None
) -> QPropertyAnimation | None:
    """让标签淡入（装/复用 ``QGraphicsOpacityEffect``）。

    Args:
        label: 目标标签。
        reduce_motion: 「减少动效」开关。

    Returns:
        开启动效时返回透明度动画；关闭动效时把 opacity 置 1.0 并返回 ``None``。
    """

    if not motion_enabled(reduce_motion):
        _apply_label_opacity(label, 1.0)
        return None

    effect = label.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(label)
        label.setGraphicsEffect(effect)
    effect.setOpacity(0.0)

    animation = QPropertyAnimation(effect, b"opacity", label)
    animation.setDuration(MOTION_LABEL_FADE_MS)
    animation.setStartValue(0.0)
    animation.setEndValue(1.0)
    animation.start()
    return animation


def _apply_label_opacity(label: QWidget, value: float) -> None:
    """把标签的透明度直接置为 ``value``（无动效终态）。"""

    effect = label.graphicsEffect()
    if not isinstance(effect, QGraphicsOpacityEffect):
        effect = QGraphicsOpacityEffect(label)
        label.setGraphicsEffect(effect)
    effect.setOpacity(value)


__all__ = [
    "MOTION_FADE_IN_MS",
    "MOTION_FADE_OUT_MS",
    "MOTION_RISE_PX",
    "MOTION_LABEL_FADE_MS",
    "motion_enabled",
    "WindowMotion",
    "create_window_motion",
    "show_window_animated",
    "fade_label_in",
]
