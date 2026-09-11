"""手部可见性 & 裁剪回归测试 —— 守护「前爪搭在透视键盘上敲击」在 **1x 真实尺寸**下真的看得见。

本轮视觉重构（参考图：圆球团子猫 + 柔和全息彩虹 + 粗黑描边）后，旧的「蜜桃粉掌垫 /
浅焦糖键帽」判色法完全失效（这些颜色已从调色板移除）。本文件改用与**新画法**对应的
等价强度判据：

* 前爪为**近白圆润爪**（唯一近白前景）→ 用近白像素的底部 y 定位爪子；
* 键帽为**彩虹粉彩方块**（唯一高饱和亮色前景）→ 用粉彩像素的底部 y 定位键盘底排。

覆盖：
* B. 实际渲染非透明像素包围盒 ⊆ ``pet_rect()``（8 表情 + 落指/抬腕峰值 + 拖拽 × 3 缩放）；
* 光晕阈值边界（睡觉/兴奋回退整窗）；
* C. 1x 下 8 表情非透明像素数、渲染哈希两两不同；
* C. 1x 下**前爪可见**，且**落指下移 / 抬腕上移**幅度达标；
* C. 1x 下**键帽被按压发生可测下沉**。

.. note::
   本文件不修改任何源码，仅通过 QImage 离屏渲染做像素级验证。
"""

from __future__ import annotations

import hashlib
from dataclasses import replace

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel, PetPose
from desktop_pet.ui.pet_renderer import (
    _GEO_HAND_LIFT_PX,
    _GEO_HAND_PRESS_PX,
    _GEO_KEY_RIGHT_BAND,
    _GEO_PAW_W,
    PetRenderer,
)
from desktop_pet.ui.pet_window import PetWindow

_SCALES = (0.8, 1.0, 1.2)


class _StubModel:
    """只暴露 :meth:`pose`，便于把任意姿态塞进 ``PetWindow``。"""

    def __init__(self, pose: PetPose) -> None:
        self._pose = pose

    def pose(self) -> PetPose:
        return self._pose


def _render(renderer: PetRenderer, pose: PetPose, scale: float) -> QImage:
    w = int(round(C.BASE_W * scale))
    h = int(round(C.BASE_H * scale))
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        renderer.paint(painter, pose, scale, QSize(w, h))
    finally:
        painter.end()
    return image


def _bbox(image: QImage) -> tuple[int, int, int, int] | None:
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        base = y * stride + 3
        for x in range(w):
            if data[base + x * 4] != 0:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    return None if max_x < 0 else (min_x, min_y, max_x, max_y)


def _opaque_count(image: QImage) -> int:
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    return sum(1 for y in range(h) for x in range(w) if data[y * stride + x * 4 + 3] != 0)


# --------------------------------------------------------------------------- #
# 峰值姿态集合（重点：抬腕峰值 lift=1.0 此前未被任何用例覆盖）
# --------------------------------------------------------------------------- #
def _happy() -> PetPose:
    return PetModel.pose_for_expression(Expression.HAPPY)


def _peak_poses() -> dict[str, PetPose]:
    base = _happy()
    return {
        "press_peak_L": replace(base, arm_l_press=1.0, finger_l_curl=1.0),
        "press_peak_R": replace(base, arm_r_press=1.0, finger_r_curl=1.0),
        "lift_peak_L": replace(base, arm_l_lift=1.0),
        "lift_peak_R": replace(base, arm_r_lift=1.0),
        "lift_peak_both": replace(base, arm_l_lift=1.0, arm_r_lift=1.0),
        "press_and_lift": replace(base, arm_l_press=1.0, finger_l_curl=1.0, arm_r_lift=1.0),
        "dangle_only": replace(base, arm_dangle=1.0),
        "dangle_plus_lift": replace(base, arm_r_lift=1.0, arm_dangle=1.0),
        "dangle_plus_press": replace(base, arm_l_press=1.0, finger_l_curl=1.0, arm_dangle=1.0),
    }


def _expression_variants() -> dict[str, PetPose]:
    out: dict[str, PetPose] = {}
    for expr in Expression:
        pose = PetModel.pose_for_expression(expr)
        out[f"{expr.name}/base"] = pose
        out[f"{expr.name}/press"] = replace(pose, arm_l_press=1.0, finger_l_curl=1.0)
        out[f"{expr.name}/lift"] = replace(pose, arm_r_lift=1.0)
    return out


def _contained(bbox: tuple[int, int, int, int], rect) -> bool:
    return (rect.left() <= bbox[0] and rect.top() <= bbox[1]
            and rect.right() >= bbox[2] and rect.bottom() >= bbox[3])


# --------------------------------------------------------------------------- #
# B ★ 裁剪回归
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("scale", _SCALES)
def test_peak_frames_not_clipped(qtbot, scale: float, capsys) -> None:
    """落指/抬腕峰值 + 拖拽叠加姿态，实际内容必须 ⊆ pet_rect()。"""

    renderer = PetRenderer()
    failures: list[str] = []
    for name, pose in _peak_poses().items():
        window = PetWindow(_StubModel(pose), renderer, scale)
        qtbot.addWidget(window)
        window.set_scale(scale)
        rect = window.pet_rect()
        bbox = _bbox(_render(renderer, pose, scale))
        assert bbox is not None, f"{name}@scale{scale} 渲染为空白"
        with capsys.disabled():
            print(f"\n[clip] s={scale} {name:<20} bbox={bbox} "
                  f"rect=({rect.left()},{rect.top()},{rect.right()},{rect.bottom()}) "
                  f"{'OK' if _contained(bbox, rect) else '**CLIP**'}")
        if not _contained(bbox, rect):
            failures.append(f"{name}@scale{scale}: bbox={bbox} rect={rect}")
    assert not failures, "峰值帧被 pet_rect() 裁剪：\n" + "\n".join(failures)


@pytest.mark.parametrize("scale", _SCALES)
def test_all_expression_variants_not_clipped(qtbot, scale: float) -> None:
    """8 表情 × {base, 落指峰值, 抬腕峰值}，内容必须 ⊆ pet_rect()。"""

    renderer = PetRenderer()
    failures: list[str] = []
    for name, pose in _expression_variants().items():
        window = PetWindow(_StubModel(pose), renderer, scale)
        qtbot.addWidget(window)
        window.set_scale(scale)
        rect = window.pet_rect()
        bbox = _bbox(_render(renderer, pose, scale))
        assert bbox is not None, f"{name}@scale{scale} 渲染为空白"
        if not _contained(bbox, rect):
            failures.append(f"{name}@scale{scale}: bbox={bbox} rect={rect}")
    assert not failures, "表情变体被 pet_rect() 裁剪：\n" + "\n".join(failures)


@pytest.mark.parametrize(
    "glow,full_window", [(0.009, False), (0.010, False), (0.011, True)]
)
def test_glow_threshold_boundary_still_intact(qtbot, glow: float, full_window: bool) -> None:
    """光晕阈值边界（睡觉/兴奋回退整窗）不应因手部放大而失效。"""

    renderer = PetRenderer()
    assert PetRenderer.GLOW_ALPHA_EPSILON == 0.01
    pose = replace(_happy(), glow_alpha=glow)
    for scale in _SCALES:
        window = PetWindow(_StubModel(pose), renderer, scale)
        qtbot.addWidget(window)
        window.set_scale(scale)
        assert (window.pet_rect() == window.rect()) is full_window
        bbox = _bbox(_render(renderer, pose, scale))
        assert bbox is not None
        assert _contained(bbox, window.pet_rect()), f"glow={glow}@scale{scale} 被裁剪"


# --------------------------------------------------------------------------- #
# C ★ 1x 真实尺寸观感
# --------------------------------------------------------------------------- #
def test_all_eight_expressions_distinct_and_nonblank_at_1x(capsys) -> None:
    renderer = PetRenderer()
    hashes: dict[str, str] = {}
    counts: dict[str, int] = {}
    for expr in Expression:
        pose = PetModel.pose_for_expression(expr)
        image = _render(renderer, pose, 1.0)
        data = bytes(image.constBits())
        hashes[expr.name] = hashlib.md5(data).hexdigest()
        counts[expr.name] = _opaque_count(image)
    with capsys.disabled():
        print("\n[1x] 表情非透明像素/哈希:")
        for name in hashes:
            print(f"    {name:<10} px={counts[name]:>6} md5={hashes[name][:10]}")
    assert all(c > 500 for c in counts.values()), f"存在空白表情：{counts}"
    assert len(set(hashes.values())) == len(hashes), "1x 下存在渲染完全相同的表情"


# --- 像素颜色判据（ARGB32 小端：byte0=B,1=G,2=R,3=A；离屏底色为全透明）--- #
def _is_white(data: bytes, stride: int, x: int, y: int) -> bool:
    """近白前爪 / 眼睛高光（唯一近白前景元素）。"""

    o = y * stride + x * 4
    if data[o + 3] == 0:
        return False
    b, g, r = data[o], data[o + 1], data[o + 2]
    return r > 232 and g > 232 and b > 232


def _is_pastel_key(data: bytes, stride: int, x: int, y: int) -> bool:
    """彩虹粉彩键帽：非透明、非近白、亮且有色彩（深灰键座 / 黑描边 / 灰抗锯齿被排除）。"""

    o = y * stride + x * 4
    if data[o + 3] == 0:
        return False
    b, g, r = data[o], data[o + 1], data[o + 2]
    if r > 232 and g > 232 and b > 232:
        return False
    return min(r, g, b) > 100 and (max(r, g, b) - min(r, g, b)) > 45


def _max_y(image: QImage, predicate, x0: int, x1: int, y0: int, y1: int) -> int | None:
    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    best: int | None = None
    for y in range(y0, min(y1, image.height())):
        for x in range(x0, min(x1, image.width())):
            if predicate(data, stride, x, y):
                best = y if best is None else max(best, y)
    return best


def _count(image: QImage, predicate, x0: int, x1: int, y0: int, y1: int) -> int:
    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    n = 0
    for y in range(y0, min(y1, image.height())):
        for x in range(x0, min(x1, image.width())):
            if predicate(data, stride, x, y):
                n += 1
    return n


# 前爪带宽（左/右）与纵向扫描带，以及键帽扫面（右端键带取自渲染常量，避免几何漂移）
_PAW_L = (50, 74)
_PAW_R = (88, 112)
_PAW_BAND = (100, 152)
_KEY_RIGHT = (int(_GEO_KEY_RIGHT_BAND[0]), int(_GEO_KEY_RIGHT_BAND[1]))
_KEY_BAND = (120, 174)

# QA 加固（非放水）：
#   「带内近白计数 >= 40」会被**前臂白芯**单独满足 —— 前臂白芯本就落在扫描带内
#   （≈84px，其圆头端还下探到 y≈130），即使整只爪子消失该用例仍会通过
#   （已用「爪子消失」变异体实测：带内近白仍有 174px > 40）。
#   爪子（``_GEO_PAW_W``=21）的白芯 ≈17px，明显**宽于**前臂白芯（``_GEO_FOREARM_W``=12px）。
#   故加固判据 = 带内**单行最长连续近白游程** >= 14px（正常态实测 16px；变异体 12px）。
_PAW_MIN_RUN_PX = 14


def _max_white_run(image: QImage, x0: int, x1: int, y0: int, y1: int) -> int:
    """扫描带内**单行最长连续近白游程**（反映「爪子比前臂宽」这一可视特征）。"""

    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    best = 0
    for y in range(y0, min(y1, image.height())):
        run = 0
        for x in range(x0, min(x1, image.width())):
            if _is_white(data, stride, x, y):
                run += 1
                if run > best:
                    best = run
            else:
                run = 0
    return best


def test_paws_visible_at_1x(capsys) -> None:
    """1x 下左右前爪（近白圆润爪）都必须可见，且**爪子明显宽于前臂**（防前臂白芯蒙混）。"""

    renderer = PetRenderer()
    image = _render(renderer, _happy(), 1.0)
    for label, band in (("left", _PAW_L), ("right", _PAW_R)):
        n = _count(image, _is_white, band[0], band[1], _PAW_BAND[0], _PAW_BAND[1])
        run = _max_white_run(image, band[0], band[1], _PAW_BAND[0], _PAW_BAND[1])
        with capsys.disabled():
            print(f"\n[1x] {label} 前爪: 近白像素={n} 单行最长游程={run}px")
        assert n >= 40, f"{label} 前爪在 1x 下不可见（{n} 像素）"
        assert run >= _PAW_MIN_RUN_PX, (
            f"{label} 爪子宽度不足（最长游程 {run}px < {_PAW_MIN_RUN_PX}），"
            f"疑似爪子消失、仅剩前臂白芯（宽 12px）"
        )


def test_press_moves_paw_down_at_1x(capsys) -> None:
    """落指（press=1）时前爪底部必须下移 ≥8px（几何常量 ``_GEO_HAND_PRESS_PX``）。"""

    renderer = PetRenderer()
    idle = _render(renderer, _happy(), 1.0)
    press = _render(renderer, replace(_happy(), arm_l_press=1.0), 1.0)
    idle_y = _max_y(idle, _is_white, _PAW_L[0], _PAW_L[1], _PAW_BAND[0], _PAW_BAND[1])
    press_y = _max_y(press, _is_white, _PAW_L[0], _PAW_L[1], _PAW_BAND[0], _PAW_BAND[1])
    assert idle_y is not None and press_y is not None, "前爪不可见，无法测量"
    dy = press_y - idle_y
    with capsys.disabled():
        print(f"\n[1x] 落指前爪底 y: idle={idle_y} press={press_y}  下移={dy}px")
    assert dy >= 8, f"落指下移仅 {dy}px（< 8 不可见）"
    assert abs(dy - _GEO_HAND_PRESS_PX) <= 2.0, (
        f"落指下移 {dy}px 与渲染常量 {_GEO_HAND_PRESS_PX}px 不符"
    )


def test_lift_raises_paw_at_1x(capsys) -> None:
    """抬腕（lift=1）时前爪底部必须上移 ≥12px（几何常量 ``_GEO_HAND_LIFT_PX``）。"""

    renderer = PetRenderer()
    idle = _render(renderer, _happy(), 1.0)
    lift = _render(renderer, replace(_happy(), arm_l_lift=1.0), 1.0)
    idle_y = _max_y(idle, _is_white, _PAW_L[0], _PAW_L[1], _PAW_BAND[0], _PAW_BAND[1])
    lift_y = _max_y(lift, _is_white, _PAW_L[0], _PAW_L[1], _PAW_BAND[0], _PAW_BAND[1])
    assert idle_y is not None and lift_y is not None, "前爪不可见，无法测量"
    dy = idle_y - lift_y
    with capsys.disabled():
        print(f"\n[1x] 抬腕前爪底 y: idle={idle_y} lift={lift_y}  上移={dy}px")
    assert dy >= 12, f"抬腕上移仅 {dy}px（< 12 不可见）"
    assert abs(dy - _GEO_HAND_LIFT_PX) <= 2.0, (
        f"抬腕上移 {dy}px 与渲染常量 {_GEO_HAND_LIFT_PX}px 不符"
    )


def test_keycaps_sink_when_pressed_at_1x(capsys) -> None:
    """右手落指（arm_r_press=1）时，右半键盘粉彩键帽底部必须下沉 ≥3px。"""

    renderer = PetRenderer()
    idle = _render(renderer, _happy(), 1.0)
    press = _render(renderer, replace(_happy(), arm_r_press=1.0), 1.0)
    idle_y = _max_y(idle, _is_pastel_key, _KEY_RIGHT[0], _KEY_RIGHT[1],
                    _KEY_BAND[0], _KEY_BAND[1])
    press_y = _max_y(press, _is_pastel_key, _KEY_RIGHT[0], _KEY_RIGHT[1],
                     _KEY_BAND[0], _KEY_BAND[1])
    assert idle_y is not None and press_y is not None, "键帽不可检出"
    dy = press_y - idle_y
    with capsys.disabled():
        print(f"\n[1x] 右键盘键帽底 y: idle={idle_y} press={press_y}  下沉={dy}px")
    assert dy >= 3, f"键帽下沉仅 {dy}px（< 3 不可见）"
