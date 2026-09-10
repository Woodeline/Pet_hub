"""UI 冒烟测试（FR-15/16/17/20/25/34 + 渲染"真的画出来了"验证）。

使用 ``pytest-qt`` 的 ``qtbot`` 提供 QApplication；``QT_QPA_PLATFORM=offscreen``
由 ``conftest.py`` 设定，不弹出真实窗口。
"""

from __future__ import annotations

import hashlib

import pytest
from PySide6.QtCore import QPoint, QSize, Qt
from PySide6.QtGui import QImage, QPainter

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel
from desktop_pet.ui.bubble import BubbleWindow
from desktop_pet.ui.pet_renderer import PetRenderer
from desktop_pet.ui.pet_window import PetWindow


# --------------------------------------------------------------------------- #
# 渲染辅助
# --------------------------------------------------------------------------- #
def render_pose(renderer: PetRenderer, pose, scale: float = 1.0) -> QImage:
    w = int(round(C.BASE_W * scale))
    h = int(round(C.BASE_H * scale))
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(0)  # 全透明
    painter = QPainter(image)
    try:
        renderer.paint(painter, pose, scale, QSize(w, h))
    finally:
        painter.end()
    return image


def opaque_stats(image: QImage) -> tuple[int, tuple[int, int, int, int]]:
    """返回 (非透明像素数, 包围盒)。"""

    w, h = image.width(), image.height()
    count = 0
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        for x in range(w):
            if image.pixelColor(x, y).alpha() > 0:
                count += 1
                min_x = min(min_x, x)
                min_y = min(min_y, y)
                max_x = max(max_x, x)
                max_y = max(max_y, y)
    return count, (min_x, min_y, max_x, max_y)


def image_hash(image: QImage) -> str:
    return hashlib.md5(bytes(image.constBits())).hexdigest()


# --------------------------------------------------------------------------- #
# 1. 窗口标志与透明属性（FR-15/16/17）
# --------------------------------------------------------------------------- #
def test_window_flags_frameless_topmost_tool(qtbot) -> None:
    window = PetWindow(PetModel(), PetRenderer(), 1.0)
    qtbot.addWidget(window)
    flags = window.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint), "缺少无边框标志 (FR-15)"
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint), "缺少置顶标志 (FR-16)"
    assert bool(flags & Qt.WindowType.Tool), "缺少 Tool 标志（不进任务栏，FR-17）"


def test_window_translucent_background(qtbot) -> None:
    window = PetWindow(PetModel(), PetRenderer(), 1.0)
    qtbot.addWidget(window)
    assert window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground), (
        "未设置 WA_TranslucentBackground (FR-15)"
    )


# --------------------------------------------------------------------------- #
# 2. 缩放（FR-20）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "scale,expect_w,expect_h",
    [(0.8, 128, 144), (1.0, 160, 180), (1.2, 192, 216)],
)
def test_set_scale_resizes_window(qtbot, scale, expect_w, expect_h) -> None:
    window = PetWindow(PetModel(), PetRenderer(), 1.0)
    qtbot.addWidget(window)
    window.set_scale(scale)
    assert (window.width(), window.height()) == (expect_w, expect_h)
    assert window.current_scale() == scale


# --------------------------------------------------------------------------- #
# 3. 帧率切换（FR-34）
# --------------------------------------------------------------------------- #
def test_set_fps_switches_timer_interval(qtbot) -> None:
    window = PetWindow(PetModel(), PetRenderer(), 1.0)
    qtbot.addWidget(window)
    for fps, expected_ms in ((30, 33), (15, 67), (8, 125)):
        window.set_fps(fps)
        assert window._timer.interval() == expected_ms, f"{fps}fps 间隔错误"


def test_interval_for_fps_helper() -> None:
    assert C.interval_for_fps(30) == 33
    assert C.interval_for_fps(15) == 67
    assert C.interval_for_fps(8) == 125
    assert C.interval_for_fps(0) >= 1  # 防除零


# --------------------------------------------------------------------------- #
# 4. 关键测试：猫真的被画出来了（非空白图）
# --------------------------------------------------------------------------- #
def test_renderer_paints_non_transparent_pet(qtbot) -> None:
    renderer = PetRenderer()
    pose = PetModel.pose_for_expression(Expression.HAPPY)
    image = render_pose(renderer, pose, 1.0)
    count, (min_x, min_y, max_x, max_y) = opaque_stats(image)

    print(f"[render] HAPPY 非透明像素={count} 包围盒={(min_x, min_y, max_x, max_y)}")
    assert count > 3000, f"绘制结果几乎为空（{count} 像素）——猫没画出来"
    # 包围盒应占据画布的可观比例
    assert (max_x - min_x) > 60, "宠物宽度异常"
    assert (max_y - min_y) > 60, "宠物高度异常"
    # 四角应为透明（证明不是整块实心底）
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(image.width() - 1, 0).alpha() == 0


def test_renderer_paints_at_all_scales(qtbot) -> None:
    renderer = PetRenderer()
    pose = PetModel.pose_for_expression(Expression.HAPPY)
    for scale in C.SCALES:
        image = render_pose(renderer, pose, scale)
        count, _ = opaque_stats(image)
        assert count > 1000, f"scale={scale} 渲染为空"


# --------------------------------------------------------------------------- #
# 5. 八种表情 + 动作姿态：零异常且彼此可区分
# --------------------------------------------------------------------------- #
def test_render_all_expressions_distinct_and_nonempty(qtbot) -> None:
    renderer = PetRenderer()
    stats: dict[str, tuple[int, tuple[int, int, int, int], str]] = {}
    for expr in Expression:
        pose = PetModel.pose_for_expression(expr)
        image = render_pose(renderer, pose, 1.0)
        count, bbox = opaque_stats(image)
        stats[expr.name] = (count, bbox, image_hash(image))
        print(f"[render] {expr.name:9s} 非透明像素={count:6d} 包围盒={bbox}")

    # 全部非空
    for name, (count, _bbox, _h) in stats.items():
        assert count > 3000, f"{name} 渲染像素过少（{count}）"

    # 两两渲染结果必须不同（视觉可区分）
    hashes = [v[2] for v in stats.values()]
    assert len(set(hashes)) == len(hashes), "存在渲染完全相同的表情"


def test_render_action_poses_no_exception(qtbot) -> None:
    renderer = PetRenderer()
    # 敲击按压姿态
    model = PetModel()
    model.press_arm()
    model.update(0.033, 1.0)
    render_pose(renderer, model.pose())

    # 拖拽被拎起姿态
    drag = PetModel()
    drag.set_dragging(True)
    drag.update(0.033, 1.0)
    render_pose(renderer, drag.pose())

    # 点击弹跳
    click = PetModel()
    click.trigger_click()
    click.update(0.1, 1.0)
    render_pose(renderer, click.pose())


# --------------------------------------------------------------------------- #
# 6. 托盘图标（FR-25）
# --------------------------------------------------------------------------- #
def test_build_tray_icon_non_null(qtbot) -> None:
    icon = PetRenderer.build_tray_icon()
    assert not icon.isNull(), "托盘图标为空"
    sizes = {size.width() for size in icon.availableSizes()}
    assert 16 in sizes and 32 in sizes, f"缺少 16/32px 图标：{sizes}"


# --------------------------------------------------------------------------- #
# 7. 气泡窗口（FR-30）
# --------------------------------------------------------------------------- #
def test_bubble_show_and_hide(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.set_anchor(QPoint(400, 300))
    bubble.show_message("你好呀~", 2.5)
    assert bubble._text == "你好呀~"
    assert bubble._duration == 2.5
    bubble.hide_bubble()
    assert bubble._phase == 0


def test_bubble_duration_is_clamped(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.show_message("x", 99.0)
    assert bubble._duration == C.BUBBLE_MAX_DURATION_S
    bubble.show_message("y", 0.01)
    assert bubble._duration == C.BUBBLE_MIN_DURATION_S


def test_bubble_empty_text_is_noop(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    bubble.show_message("first", 2.0)
    bubble.show_message("", 2.0)  # 空文本不应覆盖
    assert bubble._text == "first"


def test_bubble_window_flags(qtbot) -> None:
    bubble = BubbleWindow()
    qtbot.addWidget(bubble)
    flags = bubble.windowFlags()
    assert bool(flags & Qt.WindowType.FramelessWindowHint)
    assert bool(flags & Qt.WindowType.WindowStaysOnTopHint)
    assert bool(flags & Qt.WindowType.Tool)
    assert bubble.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


# --------------------------------------------------------------------------- #
# 8. PetWindow 绘制冒烟（painting 到 widget 不崩溃）
# --------------------------------------------------------------------------- #
def test_pet_window_paints_without_crash(qtbot) -> None:
    window = PetWindow(PetModel(), PetRenderer(), 1.0)
    qtbot.addWidget(window)
    window.show()
    window.refresh()
    qtbot.wait(30)  # 让事件循环处理一次 paintEvent
    # 无异常即通过
