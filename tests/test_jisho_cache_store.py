"""Jisho 缓存 store 单测（容错读 / 原子写 / 损坏备份 / 逐字段容错）。

**隔离要求**：所有读写都使用 ``tmp_path``，绝不触碰真实 ``%APPDATA%``。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.jisho import JishoResult
from desktop_pet.core.jisho_cache_store import JishoCacheItem, JishoCacheStore


def _result(word: str = "食べる") -> JishoResult:
    return JishoResult(
        word=word,
        readings=("たべる",),
        parts_of_speech=("Ichidan verb",),
        english_definitions=("to eat",),
        jlpt=("N5",),
        is_common=True,
    )


def _store(path: Path) -> JishoCacheStore:
    return JishoCacheStore(path)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. 写入 / 读取往返
# --------------------------------------------------------------------------- #
def test_put_get_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path / "jisho_cache.json")
    store.put("食べる", _result(), "2025-01-01T00:00:00+00:00")
    item = store.get("食べる")
    assert item is not None
    assert item.fetched_at == "2025-01-01T00:00:00+00:00"
    assert item.result == _result()


def test_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "jisho_cache.json"
    store = _store(path)
    store.put("食べる", _result(), "2025-01-01T00:00:00+00:00")
    store.put("飲む", _result("飲む"), "2025-01-02T00:00:00+00:00")

    loaded = _store(path).load()
    assert set(loaded) == {"食べる", "飲む"}
    assert loaded["食べる"].result == _result()


def test_put_empty_word_ignored(tmp_path: Path) -> None:
    store = _store(tmp_path / "jisho_cache.json")
    store.put("", _result(), "2025-01-01T00:00:00+00:00")
    assert store.load() == {}


# --------------------------------------------------------------------------- #
# 2. 容错读
# --------------------------------------------------------------------------- #
def test_missing_file_returns_empty(tmp_path: Path) -> None:
    store = _store(tmp_path / "jisho_cache.json")
    assert store.load() == {}


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "jisho_cache.json"
    _write(path, "")
    assert _store(path).load() == {}


def test_invalid_json_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "jisho_cache.json"
    _write(path, "{ not json ]")
    assert _store(path).load() == {}
    backups = list(path.parent.glob("jisho_cache.json.corrupt-*"))
    assert len(backups) == 1, f"损坏文件应被备份：{backups}"


def test_non_object_root_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "jisho_cache.json"
    _write(path, "[1, 2, 3]")
    assert _store(path).load() == {}
    assert len(list(path.parent.glob("jisho_cache.json.corrupt-*"))) == 1


def test_items_not_object_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "jisho_cache.json"
    _write(path, json.dumps({"version": 1, "items": [1, 2]}))
    assert _store(path).load() == {}
    assert len(list(path.parent.glob("jisho_cache.json.corrupt-*"))) == 1


def test_invalid_items_skipped_valid_kept(tmp_path: Path) -> None:
    path = tmp_path / "jisho_cache.json"
    good = _result()
    _write(
        path,
        json.dumps(
            {
                "version": C.JISHO_CACHE_VERSION,
                "items": {
                    "食べる": {"fetched_at": "2025-01-01T00:00:00+00:00", "result": good.to_dict()},
                    "bad": {"fetched_at": "2025-01-01T00:00:00+00:00"},  # 缺 result
                    "also-bad": "not-a-dict",
                },
            }
        ),
    )
    loaded = _store(path).load()
    assert set(loaded) == {"食べる"}
    assert loaded["食べる"].result == good


# --------------------------------------------------------------------------- #
# 3. 原子写
# --------------------------------------------------------------------------- #
def test_save_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "jisho_cache.json"
    store = _store(path)
    store.put("食べる", _result(), "2025-01-01T00:00:00+00:00")
    leftover = list(path.parent.glob("*.tmp")) + list(path.parent.glob("jisho-cache-*"))
    assert leftover == [], f"原子保存残留临时文件：{leftover}"


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "jisho_cache.json"
    store = _store(nested)
    store.put("食べる", _result(), "2025-01-01T00:00:00+00:00")
    assert nested.exists()


def test_put_overwrites_existing(tmp_path: Path) -> None:
    path = tmp_path / "jisho_cache.json"
    store = _store(path)
    store.put("食べる", _result(), "2025-01-01T00:00:00+00:00")
    store.put("食べる", _result("飲む"), "2025-01-02T00:00:00+00:00")
    loaded = _store(path).load()
    item = loaded["食べる"]
    assert item.result.word == "飲む"
    assert item.fetched_at == "2025-01-02T00:00:00+00:00"


# --------------------------------------------------------------------------- #
# 4. JishoCacheItem 序列化
# --------------------------------------------------------------------------- #
def test_cache_item_roundtrip() -> None:
    item = JishoCacheItem(fetched_at="2025-01-01T00:00:00+00:00", result=_result())
    assert JishoCacheItem.from_dict(item.to_dict()) == item


def test_cache_item_from_dict_invalid() -> None:
    assert JishoCacheItem.from_dict(None) is None
    assert JishoCacheItem.from_dict({}) is None
    assert JishoCacheItem.from_dict({"fetched_at": "x"}) is None  # 缺 result
    assert JishoCacheItem.from_dict({"result": _result().to_dict()}) is None  # 缺 fetched_at


# --------------------------------------------------------------------------- #
# 5. 默认路径（隔离 APPDATA）
# --------------------------------------------------------------------------- #
def test_default_path_uses_appdata(isolated_appdata: Path) -> None:
    path = JishoCacheStore.default_path()
    assert path == isolated_appdata / C.CONFIG_DIR_NAME / C.JISHO_CACHE_FILENAME
