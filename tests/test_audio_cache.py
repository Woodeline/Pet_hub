"""``core.audio_cache`` 单测（读写往返 / 原子写 / 容错）。"""

from __future__ import annotations

from pathlib import Path

from desktop_pet.core.audio_cache import AudioCacheStore


def _store(tmp_path: Path) -> AudioCacheStore:
    return AudioCacheStore(tmp_path / "audio_cache")


_MP3 = b"\xff\xfb" + b"\x00" * 512


def test_load_miss_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert store.load("私") is None


def test_save_load_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)

    path = store.save("私", _MP3)

    assert path is not None
    assert path.is_file()
    assert path.suffix == ".mp3"
    assert path.read_bytes() == _MP3
    assert store.load("私") == path


def test_save_creates_directory(tmp_path: Path) -> None:
    store = _store(tmp_path)
    assert not store.directory.exists()

    store.save("私", _MP3)

    assert store.directory.is_dir()


def test_path_for_is_sha1_mp3(tmp_path: Path) -> None:
    store = _store(tmp_path)

    path = store.path_for("私")

    import hashlib

    expected = hashlib.sha1("私".encode("utf-8")).hexdigest() + ".mp3"
    assert path.name == expected
    assert path.parent == store.directory


def test_save_empty_data_rejected(tmp_path: Path) -> None:
    store = _store(tmp_path)

    assert store.save("私", b"") is None
    assert store.load("私") is None


def test_save_failure_returns_none(tmp_path: Path) -> None:
    # 目录路径被一个文件占用 → mkdir 失败 → 容错返回 None（不抛）。
    occupied = tmp_path / "audio_cache"
    occupied.write_bytes(b"x")
    store = AudioCacheStore(occupied)

    assert store.save("私", _MP3) is None


def test_discard_removes_only_target(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.save("私", _MP3)
    store.save("彼", _MP3)

    store.discard("私")

    assert store.load("私") is None
    assert store.load("彼") is not None
    store.discard("私")  # 再删不抛
