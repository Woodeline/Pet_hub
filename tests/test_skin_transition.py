"""工程师自测：皮肤切换 cross-fade 过渡（ui.pet_window）。

覆盖：
1. set_skin_renderer(animate=True)：进入过渡态，过渡期 pet_rect 回退整窗；
   超过 ``SKIN_FADE_S`` 后首次重绘清除过渡态（旧渲染器随之释放）。
2. set_skin_renderer(animate=False)：直切终态（reduce_motion 路径），无过渡。
3. 同渲染器重复设置：不进过渡。
4. 过渡中两渲染器均被绘制（中间帧 grab 不崩溃、非空）。

帧图在 tmp_path 内纯 Python 生成（零图片素材红线）；时间由 monkeypatch
的 ``time.monotonic`` 替身驱动（不真实等待）。
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.pet_model import PetModel
from desktop_pet.core.skin_pack import load_skin_pack
from desktop_pet.ui import pet_window as pet_window_module
from desktop_pet.ui.pet_renderer import PetRenderer
from desktop_pet.ui.pet_window import PetWindow
from desktop_pet.ui.skin_renderer import SkinPackRenderer


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


def _build_pack(tmp_path: Path, name: str, rgb: tuple[int, int, int]) -> SkinPackRenderer:
    """生成一个最小合法皮肤包（idle 2 帧）并构造渲染器。"""

    root = tmp_path / name
    action_dir = root / "action"
    action_dir.mkdir(parents=True)
    for i in range(2):
        (action_dir / f"stand_{i}.png").write_bytes(_png_bytes(48, 56, rgb))
    (root / "pet_conf.json").write_text(
        '{"width": 48, "height": 56, "default": "idle", "drag": "idle", "fall": "idle"}',
        encoding="utf-8",
    )
    (root / "act_conf.json").write_text(
        '{"idle": {"images": "stand", "frame_refresh": 0.3}}',
        encoding="utf-8",
    )
    return SkinPackRenderer(load_skin_pack(root))


@pytest.fixture()
def window(qtbot) -> PetWindow:
    """矢量渲染起点的宠物窗口（offscreen）。"""

    win = PetWindow(PetModel(), PetRenderer(), 1.0, None)
    qtbot.addWidget(win)
    return win


class _FakeClock:
    """``time.monotonic`` 替身：可手动推进（避免真实等待过渡时长）。"""

    def __init__(self) -> None:
        self.now: float = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture()
def fake_clock(monkeypatch: pytest.MonkeyPatch) -> _FakeClock:
    clock = _FakeClock()
    monkeypatch.setattr(pet_window_module.time, "monotonic", clock)
    return clock


# --------------------------------------------------------------------------- #
# 过渡态
# --------------------------------------------------------------------------- #
def test_skin_switch_enters_and_clears_transition(
    window: PetWindow, qtbot, fake_clock: _FakeClock, tmp_path: Path
) -> None:
    """切换 → 过渡中（整窗脏区）；超过时长后重绘清除过渡态。"""

    skin_a = _build_pack(tmp_path, "cat_a", (120, 140, 200))
    skin_b = _build_pack(tmp_path, "cat_b", (200, 140, 120))
    window.set_skin_renderer(skin_a, animate=False)  # 先直切到 A（无过渡）

    window.set_skin_renderer(skin_b, animate=True)
    assert window._skin_transition is not None
    assert window._skin_transition[0] is skin_a
    assert window._skin_renderer is skin_b
    # 过渡期脏区回退整窗
    assert window.pet_rect() == window.rect()

    # 中间帧：两渲染器同绘不崩溃
    fake_clock.now += C.SKIN_FADE_S / 2
    assert not window.grab().isNull()
    assert window._skin_transition is not None  # 仍在过渡

    # 超过时长后的首次重绘：清过渡态、走终态单绘
    fake_clock.now += C.SKIN_FADE_S + 0.1
    assert not window.grab().isNull()
    assert window._skin_transition is None


def test_skin_switch_without_animate_snaps(window: PetWindow, tmp_path: Path) -> None:
    """animate=False（reduce_motion 路径）：直切终态、无过渡态。"""

    skin = _build_pack(tmp_path, "cat_snap", (90, 120, 90))
    window.set_skin_renderer(skin, animate=False)
    assert window._skin_renderer is skin
    assert window._skin_transition is None


def test_same_renderer_reused_no_transition(
    window: PetWindow, fake_clock: _FakeClock, tmp_path: Path
) -> None:
    """重复设置同一渲染器：不进过渡（避免自淡出自淡入）。"""

    skin = _build_pack(tmp_path, "cat_same", (140, 90, 90))
    window.set_skin_renderer(skin, animate=False)
    window.set_skin_renderer(skin, animate=True)
    assert window._skin_transition is None


def test_skin_to_vector_transition(window: PetWindow, fake_clock: _FakeClock, tmp_path: Path) -> None:
    """皮肤 → 矢量回落：同样进过渡，结束后完全回到矢量通道。"""

    skin = _build_pack(tmp_path, "cat_to_vec", (90, 90, 140))
    window.set_skin_renderer(skin, animate=False)
    window.set_skin_renderer(None, animate=True)
    assert window._skin_transition is not None
    fake_clock.now += C.SKIN_FADE_S + 0.1
    assert not window.grab().isNull()
    assert window._skin_transition is None
    assert window._skin_renderer is None
