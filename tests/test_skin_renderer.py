"""ui.skin_renderer 皮肤包帧图渲染通道单元测试。

帧图在 tmp_path 内用纯 Python（zlib/struct）动态生成最小合法 PNG，
仓库本身保持零图片素材（test_no_image_assets 承诺）。渲染器的绘制结果
用 QImage 光栅化后按像素抽样断言（offscreen 平台可确定性复现）。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from desktop_pet.core.skin_pack import SkinPack, load_skin_pack
from desktop_pet.ui.skin_renderer import SkinPackRenderer


# --------------------------------------------------------------------------- #
# 最小 PNG 生成（与 test_skin_pack.py 同源；RGB 真彩色）
# --------------------------------------------------------------------------- #
def _png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * width
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


@pytest.fixture()
def pack(tmp_path: Path) -> SkinPack:
    """生成一个三动作皮肤包：idle 4 帧 / drag 3 帧（act_num=2）/ fall 3 帧。"""

    root = tmp_path / "sample_cat"
    action_dir = root / "action"
    action_dir.mkdir(parents=True)
    for i, shade in enumerate((200, 190, 180, 170)):
        (action_dir / f"stand_{i}.png").write_bytes(
            _png_bytes(64, 80, (120, 140, shade))
        )
    for i, shade in enumerate((210, 190, 170)):
        (action_dir / f"drag_{i}.png").write_bytes(
            _png_bytes(70, 76, (160, 120, shade))
        )
    for i, shade in enumerate((220, 200, 180)):
        (action_dir / f"fall_{i}.png").write_bytes(
            _png_bytes(60, 84, (110, 160, shade))
        )

    (root / "pet_conf.json").write_text(
        '{"width": 64, "height": 80, "scale": 1.2, '
        '"default": "idle", "drag": "drag", "fall": "fall"}',
        encoding="utf-8",
    )
    (root / "act_conf.json").write_text(
        '{"idle": {"images": "stand", "frame_refresh": 0.25}, '
        '"drag": {"images": "drag", "act_num": 2, "frame_refresh": 0.12, "anchor": [0, 4]}, '
        '"fall": {"images": "fall", "act_num": 2, "frame_refresh": 0.12}}',
        encoding="utf-8",
    )
    return load_skin_pack(root)


# --------------------------------------------------------------------------- #
# 构造与激活
# --------------------------------------------------------------------------- #
def test_active_when_frames_load(pack: SkinPack) -> None:
    renderer = SkinPackRenderer(pack)
    assert renderer.active is True
    assert renderer.pack_name == "sample_cat"


def test_has_action_true_for_mapped_slots(pack: SkinPack) -> None:
    renderer = SkinPackRenderer(pack)
    assert renderer.has_action("default") is True
    assert renderer.has_action("drag") is True
    assert renderer.has_action("fall") is True
    # patpat 未映射 → False
    assert renderer.has_action("patpat") is False


def test_has_action_false_for_unknown_slot(pack: SkinPack) -> None:
    renderer = SkinPackRenderer(pack)
    assert renderer.has_action("focus") is False


# --------------------------------------------------------------------------- #
# 选帧：帧率与 act_num 循环复用
# --------------------------------------------------------------------------- #
def test_current_frame_idle_cycles_by_frame_refresh(pack: SkinPack) -> None:
    renderer = SkinPackRenderer(pack)
    # idle 4 帧，frame_refresh=0.25s → 相位每 0.25s 前进一帧
    pix0, anchor0 = renderer.current_frame("default", 0.0)
    pix1, _ = renderer.current_frame("default", 0.25)
    pix2, _ = renderer.current_frame("default", 0.50)
    assert pix0 is not None and pix1 is not None and pix2 is not None
    # 帧内容不同（不同 shade）→ 不同 QPixmap 缓存键，但这里用帧路径间接验证：
    # 直接断言三帧互不相等（通过 toImage 像素抽样式，避免比较对象同一性）。
    assert _pixmap_key(pix0) != _pixmap_key(pix1) != _pixmap_key(pix2)
    assert anchor0 == (0, 0)  # idle 无 anchor


def test_current_frame_wraps_after_full_cycle(pack: SkinPack) -> None:
    renderer = SkinPackRenderer(pack)
    # idle 4 帧 * 0.25s = 1.0s 一个完整循环；相位 1.0 → 回到第 0 帧
    pix_at_0, _ = renderer.current_frame("default", 0.0)
    pix_at_wrap, _ = renderer.current_frame("default", 1.0)
    assert _pixmap_key(pix_at_0) == _pixmap_key(pix_at_wrap)


def test_drag_act_num_expands_frames(pack: SkinPack) -> None:
    renderer = SkinPackRenderer(pack)
    # drag 3 帧 * act_num 2 = 6 帧播放序列，frame_refresh=0.12
    # 相位 0.0 与相位 0.36（第 3 帧，即第 0 帧的第 2 次循环）应相同
    pix_0, anchor = renderer.current_frame("drag", 0.0)
    pix_3, _ = renderer.current_frame("drag", 0.36)
    assert anchor == (0, 4)  # drag 定义了 anchor [0,4]
    assert _pixmap_key(pix_0) == _pixmap_key(pix_3)


def test_current_frame_unknown_slot_returns_none(pack: SkinPack) -> None:
    renderer = SkinPackRenderer(pack)
    pix, anchor = renderer.current_frame("focus", 0.0)
    assert pix is None
    assert anchor == (0, 0)


# --------------------------------------------------------------------------- #
# 绘制：光栅化后像素抽样
# --------------------------------------------------------------------------- #
def test_paint_draws_frame_to_image(qtbot, pack: SkinPack) -> None:  # noqa: ARG001
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    renderer = SkinPackRenderer(pack)
    img = QImage(64, 80, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    try:
        renderer.paint(painter, "default", 0.0, 1.0)
    finally:
        painter.end()

    # 帧图 stand_0 是纯色 (120,140,200)，中心点应命中该色（非透明）。
    center = img.pixelColor(32, 40)
    assert center.alpha() > 0
    assert (center.red(), center.green(), center.blue()) == (120, 140, 200)


def test_paint_unknown_slot_leaves_canvas_blank(qtbot, pack: SkinPack) -> None:  # noqa: ARG001
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    renderer = SkinPackRenderer(pack)
    img = QImage(64, 80, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    try:
        renderer.paint(painter, "focus", 0.0, 1.0)
    finally:
        painter.end()

    center = img.pixelColor(32, 40)
    assert center.alpha() == 0  # 未画任何帧 → 全透明


def test_paint_applies_anchor_offset(qtbot, pack: SkinPack) -> None:  # noqa: ARG001
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    renderer = SkinPackRenderer(pack)
    # drag 帧 70×76，anchor (0,4)；画布取 70×84 以容纳下移
    img = QImage(70, 84, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    try:
        renderer.paint(painter, "drag", 0.0, 1.0)
    finally:
        painter.end()

    # anchor y=4 → 帧图顶部从 y=4 开始；y=2 应仍透明，y=6 应命中 drag_0 色 (160,120,210)
    top_blank = img.pixelColor(35, 2)
    below_anchor = img.pixelColor(35, 6)
    assert top_blank.alpha() == 0
    assert below_anchor.alpha() > 0
    assert (below_anchor.red(), below_anchor.green(), below_anchor.blue()) == (160, 120, 210)


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def _pixmap_key(pixmap) -> tuple[int, int, int, int]:
    """返回 pixmap 中心像素的 RGBA 四元组，用于跨对象比较「是否为同一帧」。"""

    img = pixmap.toImage()
    c = img.pixelColor(img.width() // 2, img.height() // 2)
    return (c.red(), c.green(), c.blue(), c.alpha())
