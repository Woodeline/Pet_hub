"""手部可见性 & 裁剪回归测试 —— 守护「双手敲迷你键盘」在 **1x 真实尺寸**下真的看得见。

本轮重构把手掌从 14×11 放大到 20×14、手指 4×7 → 6×10，手掌中心下移到 y=148，
并新增迷你键盘。手的包围盒极易算窄，且 1x 是用户实际看到的尺寸（窗口 160×180）。

覆盖：
* B. 实际渲染非透明像素包围盒 ⊆ ``pet_rect()``（8 表情 + 落指峰值 + 抬腕峰值
     + 拖拽 + 悬停 × 3 档缩放）—— 重点补测**此前未被覆盖的抬腕峰值帧**；
* 光晕阈值边界（睡觉/兴奋回退整窗）；
* C. 1x 下 8 表情非透明像素数、渲染哈希两两不同；
* C. 1x 下手掌下方存在 **3 个相互分离**的手指色块，并给出每根手指像素宽度。

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
from desktop_pet.ui.pet_renderer import PetRenderer
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


# --- 像素颜色分类（ARGB32 小端：byte0=B,1=G,2=R,3=A）--- #
_PALETTE = {
    "cream": (230, 244, 255),      # #FFF4E6 → B,G,R
    "caramel": (154, 199, 242),    # #F2C79A
    "warm_brown": (79, 107, 139),  # #8B6B4F
    "peach": (168, 184, 247),      # #F7B8A8
    "dark_brown": (51, 64, 90),    # #5A4033
}


def _classify(data: bytes, stride: int, x: int, y: int) -> str:
    o = y * stride + x * 4
    if data[o + 3] == 0:
        return "transparent"
    b, g, r = data[o], data[o + 1], data[o + 2]
    best = min(_PALETTE, key=lambda k: (r - _PALETTE[k][2]) ** 2
               + (g - _PALETTE[k][1]) ** 2 + (b - _PALETTE[k][0]) ** 2)
    return best


def _cream_runs(data: bytes, stride: int, y: int, x0: int, x1: int) -> list[tuple[int, int]]:
    """返回该行 ``[x0, x1)`` 内宽度 ≥2 的 cream 连续段 ``(start, width)``。"""

    runs: list[tuple[int, int]] = []
    x = x0
    while x < x1:
        if _classify(data, stride, x, y) == "cream":
            start = x
            while x < x1 and _classify(data, stride, x, y) == "cream":
                x += 1
            width = x - start
            if width >= 2:
                runs.append((start, width))
        else:
            x += 1
    return runs


def _finger_rows(image: QImage, hand_x: float) -> tuple[int, list[list[tuple[int, int]]]]:
    """在给定手掌中心附近扫描，返回“恰好 3 段 cream”的行数与这些行的段列表。"""

    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    x0, x1 = int(hand_x - 16), int(hand_x + 16)
    good_rows: list[list[tuple[int, int]]] = []
    good_y: list[int] = []
    for y in range(int(C.BASE_H * 0.80), int(C.BASE_H) + 1):
        if y >= image.height():
            break
        runs = _cream_runs(data, stride, y, x0, x1)
        if len(runs) == 3 and all(2 <= w <= 7 for _, w in runs):
            good_rows.append(runs)
            good_y.append(y)
    if not good_y:
        return 0, []
    # 返回中间一行作为代表
    mid = good_rows[len(good_rows) // 2]
    return len(good_y), mid


def test_three_separated_fingers_visible_at_1x(capsys) -> None:
    """1x 下每只手的手掌下方必须存在 **3 个相互分离** 的 cream 手指色块。

    手指宽 6px，1x 下应为明显竖条（不能被 outline 粘连成一片）。同时给出每根手指
    的像素宽度与中心间距（应≈``_GEO_FINGER_DX``=6）。
    """

    renderer = PetRenderer()
    pose = _happy()  # 无 curl → 手指完全伸展
    image = _render(renderer, pose, 1.0)

    for label, hand_x in (("left", 56.0), ("right", 104.0)):
        n_rows, runs = _finger_rows(image, hand_x)
        with capsys.disabled():
            print(f"\n[1x] {label} 手: 检测到 {n_rows} 行含 3 段分离手指色块")
            if runs:
                centers = [s + w / 2.0 for s, w in runs]
                print(f"     代表行 runs={runs}  中心={centers}  "
                      f"间距={[round(b - a, 1) for a, b in zip(centers, centers[1:])]}  "
                      f"宽度={[w for _, w in runs]}")
        assert n_rows >= 2, f"{label} 手在 1x 下未检出 3 段分离手指（检出 {n_rows} 行）"
        assert len(runs) == 3, f"{label} 手代表行手指数 != 3：{runs}"
        widths = [w for _, w in runs]
        assert all(2 <= w <= 7 for w in widths), f"{label} 手指宽度异常：{widths}"
        centers = [s + w / 2.0 for s, w in runs]
        gaps = [b - a for a, b in zip(centers, centers[1:])]
        assert all(4.5 <= g <= 7.5 for g in gaps), f"{label} 手指中心间距异常：{gaps}"


def test_fingers_remain_visible_when_curled_at_1x() -> None:
    """落指（curl=1）时手指缩短，但仍必须可见（不得消失）。"""

    renderer = PetRenderer()
    pose = replace(_happy(), arm_l_press=1.0, finger_l_curl=1.0)
    image = _render(renderer, pose, 1.0)
    # 落指时掌心中线下移 9px，扫描更宽的 y 带
    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    max_runs = 0
    for y in range(int(C.BASE_H * 0.80), image.height()):
        runs = _cream_runs(data, stride, y, 40, 72)
        max_runs = max(max_runs, len(runs))
    assert max_runs >= 3, f"落指态下左手手指不可见（最多 {max_runs} 段）"
