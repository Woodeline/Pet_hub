"""QA 补充回归 —— 视觉重构**新增元素**（左下角鼠标 / 左侧粗尾巴 / 斜放透视键盘）的
可见性与不裁剪守护（FR-35）。

背景：本轮把 ``pet_renderer`` 整体重写，新增了左下角鼠标、大幅加粗的尾巴，并把键盘改成
约 -10° 斜放的四边形（比旧版更向右 / 向下伸展）。``test_dirty_rect_no_clip.py`` 只校验
**全部内容的并集包围盒** ⊆ ``pet_rect()`` —— 它能发现「被裁」，但**无法**发现「新元素
根本没画出来」。本文件补上：

1. 1x 下鼠标 / 尾巴 / 键盘键帽**确实存在**（按特征色统计像素数，排除「悄悄消失」）；
2. 鼠标 / 尾巴 / 键盘三者的**像素区域分别** ⊆ ``PetRenderer.body_bounds()``（3 档缩放），
   即脏矩形确实把新元素囊括其中（而非仅并集巧合覆盖）。

.. note::
   本文件不修改任何源码，仅通过 QImage 离屏渲染做像素级验证。
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QImage, QPainter

from desktop_pet.core import constants as C
from desktop_pet.core.constants import Expression
from desktop_pet.core.pet_model import PetModel, PetPose
from desktop_pet.ui.pet_renderer import PetRenderer

_SCALES = (0.8, 1.0, 1.2)

# 特征区（1x 逻辑坐标）
_MOUSE_ROI = (0, 45, 140, 180)     # 左下角鼠标
_TAIL_ROI = (0, 52, 70, 126)       # 左侧尾巴（部分被身体遮挡）
_KEY_ROI = (18, 152, 108, 180)     # 键盘


def _render(pose: PetPose, scale: float) -> QImage:
    w = int(round(C.BASE_W * scale))
    h = int(round(C.BASE_H * scale))
    image = QImage(w, h, QImage.Format.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    try:
        PetRenderer().paint(painter, pose, scale, QSize(w, h))
    finally:
        painter.end()
    return image


def _is_mouse_gray(r: int, g: int, b: int) -> bool:
    return abs(r - g) < 12 and abs(g - b) < 12 and 40 <= r <= 160


def _is_colorful(r: int, g: int, b: int) -> bool:
    return min(r, g, b) > 90 and (max(r, g, b) - min(r, g, b)) > 50


def _region_stats(image: QImage, roi, pred):
    """返回 (计数, bbox)。bbox=(minx,miny,maxx,maxy) 或 None。"""

    x0, x1, y0, y1 = roi
    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    data = bytes(image.constBits())
    n = 0
    minx, miny, maxx, maxy = w, h, -1, -1
    for y in range(y0, min(y1, h)):
        base = y * stride
        for x in range(x0, min(x1, w)):
            o = base + x * 4
            if data[o + 3] == 0:
                continue
            if pred(data[o + 2], data[o + 1], data[o]):
                n += 1
                minx, miny = min(minx, x), min(miny, y)
                maxx, maxy = max(maxx, x), max(maxy, y)
    return n, (None if maxx < 0 else (minx, miny, maxx, maxy))


def _contained(bbox, rect) -> bool:
    return (rect.left() <= bbox[0] and rect.top() <= bbox[1]
            and rect.right() >= bbox[2] and rect.bottom() >= bbox[3])


def _happy() -> PetPose:
    return PetModel.pose_for_expression(Expression.HAPPY)


def test_mouse_tail_and_keys_present_at_1x(capsys) -> None:
    """1x 下鼠标 / 尾巴 / 键盘键帽都必须真实绘制（防止「静默消失」）。"""

    image = _render(_happy(), 1.0)
    mouse_n, mouse_bb = _region_stats(image, _MOUSE_ROI, _is_mouse_gray)
    tail_n, tail_bb = _region_stats(image, _TAIL_ROI, _is_colorful)
    key_n, key_bb = _region_stats(image, _KEY_ROI, _is_colorful)
    with capsys.disabled():
        print(f"\n[new-elements] 1x 鼠标灰={mouse_n} bbox={mouse_bb}")
        print(f"[new-elements] 1x 尾巴彩色={tail_n} bbox={tail_bb}")
        print(f"[new-elements] 1x 键盘键帽彩色={key_n} bbox={key_bb}")
    assert mouse_n >= 150, f"左下角鼠标不可见（灰像素 {mouse_n}）"
    assert tail_n >= 150, f"左侧尾巴不可见（彩色像素 {tail_n}）"
    assert key_n >= 150, f"键盘彩色键帽不足（{key_n}）"


@pytest.mark.parametrize("scale", _SCALES)
def test_new_element_regions_within_dirty_rect(scale: float, capsys) -> None:
    """鼠标 / 尾巴 / 键盘的像素区域必须**分别** ⊆ body_bounds()（脏矩形不裁新元素）。"""

    pose = _happy()
    image = _render(pose, scale)
    rect = PetRenderer.body_bounds(pose, scale)
    for label, roi, pred in (
        ("mouse", _MOUSE_ROI, _is_mouse_gray),
        ("tail", _TAIL_ROI, _is_colorful),
        ("keyboard", _KEY_ROI, _is_colorful),
    ):
        n, bb = _region_stats(
            image,
            tuple(int(v * scale) for v in roi),
            pred,
        )
        with capsys.disabled():
            print(f"\n[new-elements] s={scale} {label:<9} n={n} bbox={bb} "
                  f"dirty=({rect.left()},{rect.top()},{rect.right()},{rect.bottom()})")
        assert bb is not None, f"{label}@{scale} 未检出（元素缺失）"
        assert _contained(bb, rect), f"{label}@{scale} 被 body_bounds 裁剪：{bb} ⊄ {rect}"
