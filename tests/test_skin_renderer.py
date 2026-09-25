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


def test_paint_oversized_pack_fits_base_canvas(qtbot, tmp_path: Path) -> None:  # noqa: ARG001
    """声明画布超出 BASE（DyberPet 社区包 200px 级）：加载有警告、绘制等比缩进画布。"""

    from desktop_pet.core import constants as C
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter

    root = tmp_path / "big_cat"
    action_dir = root / "action"
    action_dir.mkdir(parents=True)
    # 帧图与声明画布同尺寸（社区包惯例：300×320，实际渲染时统一缩到 fitted）
    (action_dir / "stand_0.png").write_bytes(_png_bytes(300, 320, (120, 140, 200)))
    (action_dir / "drag_0.png").write_bytes(_png_bytes(300, 320, (160, 120, 200)))
    (action_dir / "fall_0.png").write_bytes(_png_bytes(300, 320, (110, 160, 200)))
    (root / "pet_conf.json").write_text(
        '{"width": 300, "height": 320, "scale": 1.0, '
        '"default": "default", "drag": "drag", "fall": "fall"}',
        encoding="utf-8",
    )
    (root / "act_conf.json").write_text(
        '{"default": {"images": "stand"}, '
        '"drag": {"images": "drag"}, "fall": {"images": "fall"}}',
        encoding="utf-8",
    )
    pack = load_skin_pack(root)
    assert pack.warnings  # 超限警告已产生

    renderer = SkinPackRenderer(pack)
    assert renderer.active is True
    img = QImage(int(C.BASE_W), int(C.BASE_H), QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    painter = QPainter(img)
    try:
        renderer.paint(painter, "default", 0.0, 1.0)
    finally:
        painter.end()

    # fitted 160×170.67：帧等比铺满宽度，中心命中帧色
    center = img.pixelColor(int(C.BASE_W) // 2, int(C.BASE_H) // 2)
    assert center.alpha() > 0
    assert (center.red(), center.green(), center.blue()) == (120, 140, 200)
    # 右下角留白（170.67 < 180 高度方向未铺满）
    corner = img.pixelColor(int(C.BASE_W) - 1, int(C.BASE_H) - 1)
    assert corner.alpha() == 0


def test_lazy_load_keeps_unmapped_actions_out_of_cache(pack: SkinPack) -> None:
    """只预载 action_map 引用的动作；未引用动作的帧在首次用到时才进缓存。"""

    renderer = SkinPackRenderer(pack)
    # fixture 包 action_map = {default: idle, drag: drag, fall: fall}，
    # idle 的 4 帧 + drag 3 帧 + fall 3 帧 = 10 帧已预载；未映射动作不存在。
    assert len(renderer._frames) == 10
    assert all(p is not None for p in renderer._frames.values())


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


# --------------------------------------------------------------------------- #
# 包选择：build_skin_renderer(preferred) / available_skin_packs
# --------------------------------------------------------------------------- #
def _make_min_pack(root: Path, rgb: tuple[int, int, int]) -> Path:
    """在 root 下生成一个最小合法皮肤包（含必需三槽位）。"""

    action = root / "action"
    action.mkdir(parents=True)
    for prefix in ("stand", "drag", "fall"):
        (action / f"{prefix}_0.png").write_bytes(_png_bytes(64, 80, rgb))
    (root / "pet_conf.json").write_text(
        '{"width": 64, "height": 80, "default": "default", '
        '"drag": "drag", "fall": "fall"}',
        encoding="utf-8",
    )
    (root / "act_conf.json").write_text(
        '{"default": {"images": "stand"}, '
        '"drag": {"images": "drag"}, "fall": {"images": "fall"}}',
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def skins_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 skins_dir() 重定向到临时投放区，并放入两个包（AAA 在小写排序在前）。"""

    from desktop_pet.core import paths

    root = tmp_path / "skins"
    root.mkdir()
    _make_min_pack(root / "AAA", (10, 20, 30))
    _make_min_pack(root / "ZZZ", (200, 210, 220))
    monkeypatch.setattr(paths, "skins_dir", lambda: root)
    return root


def test_available_skin_packs_lists_valid_only(skins_root: Path) -> None:
    """列出通过校验的包；损坏包不入列。"""

    from desktop_pet.ui.skin_renderer import available_skin_packs

    (skins_root / "Broken").mkdir()
    (skins_root / "Broken" / "pet_conf.json").write_text("{}", encoding="utf-8")
    assert available_skin_packs() == ["AAA", "ZZZ"]


def test_build_auto_picks_first_alphabetically(skins_root: Path) -> None:
    from desktop_pet.ui.skin_renderer import build_skin_renderer

    r = build_skin_renderer("")
    assert r is not None and r.pack_name == "AAA"


def test_build_preferred_selects_named_pack(skins_root: Path) -> None:
    """指定包名优先（解决「多包共存时只能取首个」）。"""

    from desktop_pet.ui.skin_renderer import build_skin_renderer

    r = build_skin_renderer("ZZZ")
    assert r is not None and r.pack_name == "ZZZ"


def test_build_vector_returns_none(skins_root: Path) -> None:
    """显式矢量：即使有可用包也不加载。"""

    from desktop_pet.ui.skin_renderer import build_skin_renderer

    assert build_skin_renderer("vector") is None


def test_build_unknown_name_falls_back_to_auto(skins_root: Path) -> None:
    """指定包不存在 → 回落自动选择（不抛异常）。"""

    from desktop_pet.ui.skin_renderer import build_skin_renderer

    r = build_skin_renderer("NoSuchPack")
    assert r is not None and r.pack_name == "AAA"


def test_build_empty_dir_returns_none(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无 skins/ 目录 → 返回 None（调用方回落矢量）。"""

    from desktop_pet.core import paths
    from desktop_pet.ui.skin_renderer import build_skin_renderer

    monkeypatch.setattr(paths, "skins_dir", lambda: tmp_path / "nope")
    assert build_skin_renderer("") is None
