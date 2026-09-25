"""core.skin_pack 皮肤包加载器单元测试。

帧图在 tmp_path 内用纯 Python（zlib/struct）动态生成最小合法 PNG，
仓库本身保持零图片素材（test_no_image_assets 承诺）。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.skin_pack import SkinPack, SkinPackError, load_skin_pack


# --------------------------------------------------------------------------- #
# 最小 PNG 生成（RGB 真彩色，够加载器做文件存在性校验即可）
# --------------------------------------------------------------------------- #
def _png_bytes(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    row = b"\x00" + bytes(rgb) * width  # 每行前缀 filter byte 0
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(row * height))
        + chunk(b"IEND", b"")
    )


def _make_pack(
    tmp_path: Path,
    *,
    pet_conf_mutate: dict | None = None,
    act_conf_mutate: dict | None = None,
) -> Path:
    """生成一个通过校验的基线皮肤包，返回其根目录。

    基线：idle 4 帧（act_num 默认 1）、drag/fall 各 3 帧（act_num=2）。
    """

    root = tmp_path / "sample_cat"
    action_dir = root / "action"
    action_dir.mkdir(parents=True)
    for i, shade in enumerate((200, 190, 180, 170)):
        (action_dir / f"stand_{i}.png").write_bytes(_png_bytes(64, 80, (120, 140, shade)))
    for i, shade in enumerate((210, 190, 170)):
        (action_dir / f"drag_{i}.png").write_bytes(_png_bytes(70, 76, (160, 120, shade)))
    for i, shade in enumerate((220, 200, 180)):
        (action_dir / f"fall_{i}.png").write_bytes(_png_bytes(60, 84, (110, 160, shade)))

    pet_conf: dict = {
        "width": 64,
        "height": 80,
        "scale": 1.2,
        "default": "idle",
        "drag": "drag",
        "fall": "fall",
    }
    act_conf: dict = {
        "idle": {"images": "stand", "frame_refresh": 0.25},
        "drag": {"images": "drag", "act_num": 2, "frame_refresh": 0.12, "anchor": [0, 4]},
        "fall": {"images": "fall", "act_num": 2, "frame_refresh": 0.12},
    }
    if pet_conf_mutate:
        pet_conf.update(pet_conf_mutate)
    if act_conf_mutate:
        act_conf.update(act_conf_mutate)

    import json

    (root / "pet_conf.json").write_text(
        json.dumps(pet_conf, ensure_ascii=False), encoding="utf-8"
    )
    (root / "act_conf.json").write_text(
        json.dumps(act_conf, ensure_ascii=False), encoding="utf-8"
    )
    return root


# --------------------------------------------------------------------------- #
# 正向：加载 / schema / act_num 复用
# --------------------------------------------------------------------------- #
def test_load_baseline_pack_ok(tmp_path: Path) -> None:
    pack = load_skin_pack(_make_pack(tmp_path))

    assert isinstance(pack, SkinPack)
    assert pack.name == "sample_cat"
    assert (pack.width, pack.height) == (64, 80)
    assert pack.scale == 1.2
    assert pack.warnings == ()
    # 槽位路由（全局层）
    assert pack.action_map == {"default": "idle", "drag": "drag", "fall": "fall"}
    # 职责边界：动作层只出现在 actions，路由层只出现在 action_map
    assert set(pack.actions) == {"idle", "drag", "fall"}


def test_act_num_expands_frame_reuse(tmp_path: Path) -> None:
    """act_num 机制：1 套 3 帧 × 循环 2 次 = 6 帧播放序列（帧复用，无冗余资源）。"""

    pack = load_skin_pack(_make_pack(tmp_path))

    idle = pack.action_for("default")
    assert idle is not None
    assert idle.act_num == 1  # 未写 act_num → 默认 1
    assert idle.expanded_frames == (
        "stand_0.png", "stand_1.png", "stand_2.png", "stand_3.png",
    )

    drag = pack.action_for("drag")
    assert drag is not None
    assert drag.act_num == 2
    assert drag.frames == ("drag_0.png", "drag_1.png", "drag_2.png")
    assert drag.expanded_frames == (
        "drag_0.png", "drag_1.png", "drag_2.png",
        "drag_0.png", "drag_1.png", "drag_2.png",
    )
    assert drag.frame_refresh_s == 0.12
    assert drag.anchor == (0, 4)

    fall = pack.action_for("fall")
    assert fall is not None
    assert len(fall.expanded_frames) == 6


def test_defaults_applied(tmp_path: Path) -> None:
    """缺省 scale / act_num / frame_refresh / anchor 时取模块默认值。"""

    root = tmp_path / "mini"
    (root / "action").mkdir(parents=True)
    for i in range(2):
        (root / "action" / f"s_{i}.png").write_bytes(_png_bytes(32, 32, (10, 20, 30)))
    import json

    (root / "pet_conf.json").write_text(
        json.dumps({"width": 32, "height": 32, "default": "a", "drag": "a", "fall": "a"}),
        encoding="utf-8",
    )
    (root / "act_conf.json").write_text(
        json.dumps({"a": {"images": "s"}}), encoding="utf-8"
    )

    pack = load_skin_pack(root)
    assert pack.scale == 1.0
    spec = pack.actions["a"]
    assert (spec.act_num, spec.frame_refresh_s, spec.anchor) == (1, 0.2, (0, 0))
    # 三槽位映射到同一动作是合法的（最小动作集可全部复用一套帧）
    assert pack.action_for("drag") is spec


def test_unmapped_slot_returns_none(tmp_path: Path) -> None:
    pack = load_skin_pack(_make_pack(tmp_path))
    assert pack.action_for("patpat") is None  # 已知槽位但未映射


# --------------------------------------------------------------------------- #
# 反向：schema 违例 fail-fast
# --------------------------------------------------------------------------- #
def test_missing_required_slot_raises(tmp_path: Path) -> None:
    root = _make_pack(tmp_path)
    import json

    pet = json.loads((root / "pet_conf.json").read_text(encoding="utf-8"))
    del pet["fall"]
    (root / "pet_conf.json").write_text(json.dumps(pet), encoding="utf-8")

    with pytest.raises(SkinPackError) as exc_info:
        load_skin_pack(root)
    assert any("fall" in issue for issue in exc_info.value.issues)


def test_slot_referencing_undefined_action_raises(tmp_path: Path) -> None:
    root = _make_pack(tmp_path, pet_conf_mutate={"fall": "ghost"})
    with pytest.raises(SkinPackError) as exc_info:
        load_skin_pack(root)
    assert any("ghost" in issue for issue in exc_info.value.issues)


def test_missing_frames_raises(tmp_path: Path) -> None:
    root = _make_pack(tmp_path, act_conf_mutate={"fall": {"images": "ghost"}})
    with pytest.raises(SkinPackError) as exc_info:
        load_skin_pack(root)
    assert any("ghost" in issue for issue in exc_info.value.issues)


def test_canvas_over_base_warns_and_fits(tmp_path: Path) -> None:
    """画布超出程序画布（BASE_W/BASE_H）不再致命：记警告、保留原值，渲染层等比适配。"""

    root = _make_pack(
        tmp_path, pet_conf_mutate={"width": C.BASE_W + 1, "height": C.BASE_H + 1}
    )
    pack = load_skin_pack(root)
    assert pack.width == C.BASE_W + 1
    assert pack.height == C.BASE_H + 1
    assert any(str(C.BASE_W) in w for w in pack.warnings)
    assert any(str(C.BASE_H) in w for w in pack.warnings)


def test_fitted_size_scales_and_clamps(tmp_path: Path) -> None:
    """fitted_size = width×height × scale，超出画布时等比收缩到铺满较短边。"""

    import math

    # 未超限：显示尺寸 = 声明尺寸 × scale（64×80 × 1.2 = 76.8×96）
    pack = load_skin_pack(_make_pack(tmp_path))
    assert pack.fitted_size(C.BASE_W, C.BASE_H) == (76.8, 96.0)

    # 超限（DyberPet 社区包典型：300×320）：铺满 160 宽边 → 160×170.67
    big = load_skin_pack(
        _make_pack(tmp_path / "big", pet_conf_mutate={"width": 300, "height": 320})
    )
    fw, fh = big.fitted_size(C.BASE_W, C.BASE_H)
    assert math.isclose(fw, 160.0)
    assert math.isclose(fh, 170.6667, abs_tol=1e-3)
    # 宽高比保持
    assert math.isclose(fw / fh, 300 / 320, rel_tol=1e-3)


def test_fitted_size_upscales_when_scale_larger(tmp_path: Path) -> None:
    """小画布 + 大 scale：scale 生效放大，但不超过程序画布（如 Fungi 130×1.5→160）。"""

    pack = load_skin_pack(
        _make_pack(tmp_path / "f", pet_conf_mutate={"width": 130, "height": 130,
                                                    "scale": 1.5})
    )
    fw, fh = pack.fitted_size(C.BASE_W, C.BASE_H)
    assert fw == float(C.BASE_W)  # 195 超出 → 收缩到 160
    assert fh == float(C.BASE_W)


@pytest.mark.parametrize("bad", [0, -1, 1.5, True])
def test_invalid_act_num_raises(tmp_path: Path, bad) -> None:
    root = _make_pack(tmp_path, act_conf_mutate={"fall": {"images": "fall", "act_num": bad}})
    with pytest.raises(SkinPackError):
        load_skin_pack(root)


def test_nonpositive_frame_refresh_raises(tmp_path: Path) -> None:
    root = _make_pack(
        tmp_path, act_conf_mutate={"fall": {"images": "fall", "frame_refresh": 0}}
    )
    with pytest.raises(SkinPackError):
        load_skin_pack(root)


def test_images_with_path_separator_raises(tmp_path: Path) -> None:
    root = _make_pack(tmp_path, act_conf_mutate={"fall": {"images": "../evil"}})
    with pytest.raises(SkinPackError):
        load_skin_pack(root)


def test_missing_conf_file_raises(tmp_path: Path) -> None:
    root = _make_pack(tmp_path)
    (root / "act_conf.json").unlink()
    with pytest.raises(SkinPackError) as exc_info:
        load_skin_pack(root)
    assert any("act_conf.json" in issue for issue in exc_info.value.issues)


def test_malformed_json_raises(tmp_path: Path) -> None:
    root = _make_pack(tmp_path)
    (root / "pet_conf.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(SkinPackError):
        load_skin_pack(root)


def test_nonexistent_dir_raises(tmp_path: Path) -> None:
    with pytest.raises(SkinPackError):
        load_skin_pack(tmp_path / "nope")


# --------------------------------------------------------------------------- #
# 容忍路径：未知键 / 断档帧 → 警告不阻断
# --------------------------------------------------------------------------- #
def test_unknown_keys_warn_not_fail(tmp_path: Path) -> None:
    root = _make_pack(
        tmp_path,
        pet_conf_mutate={"custom_future_key": 1},
        act_conf_mutate={"fall": {"images": "fall", "future_field": True}},
    )
    pack = load_skin_pack(root)
    assert any("custom_future_key" in w for w in pack.warnings)
    assert any("future_field" in w for w in pack.warnings)


def test_noncontiguous_frames_ignored_with_warning(tmp_path: Path) -> None:
    root = _make_pack(tmp_path)
    # stand_5 存在但 3→4 断档（stand_3 之后没有 4）→ 5 被忽略并警告
    (root / "action" / "stand_5.png").write_bytes(_png_bytes(64, 80, (1, 2, 3)))

    pack = load_skin_pack(root)
    idle = pack.action_for("default")
    assert idle is not None
    assert idle.frames == ("stand_0.png", "stand_1.png", "stand_2.png", "stand_3.png")
    assert any("stand_5.png" in w for w in pack.warnings)
