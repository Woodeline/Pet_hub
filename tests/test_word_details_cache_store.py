"""``core.word_details_cache_store`` 单测（容错读 / 原子写 / 损坏备份 / 逐字段容错）。

**隔离要求**：所有读写都使用 ``tmp_path``，绝不触碰真实 ``%APPDATA%``。
"""

from __future__ import annotations

import json
from pathlib import Path

from desktop_pet.core import constants as C
from desktop_pet.core.word_detail import Collocation, Example, WordDetail
from desktop_pet.core.word_details_cache_store import (
    WordDetailsCacheItem,
    WordDetailsCacheStore,
)


def _detail(meaning: str = "我") -> WordDetail:
    return WordDetail(
        meaning_zh=(meaning,),
        pos_zh=("代词",),
        collocations=(Collocation("私は…", "自我介绍"),),
        examples=(Example("私は学生です。", "我是学生。"),),
        usage_note_zh="正式、通用。",
    )


def _store(path: Path) -> WordDetailsCacheStore:
    return WordDetailsCacheStore(path)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. 写入 / 读取往返
# --------------------------------------------------------------------------- #
def test_put_get_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path / "word_details_cache.json")
    store.put("n5-0001", _detail(), "2025-01-01T00:00:00Z")
    item = store.get("n5-0001")
    assert item is not None
    assert item.fetched_at == "2025-01-01T00:00:00Z"
    assert item.detail == _detail()


def test_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "word_details_cache.json"
    store = _store(path)
    store.put("n5-0001", _detail("我"), "2025-01-01T00:00:00Z")
    store.put("n5-0002", _detail("你"), "2025-01-02T00:00:00Z")

    loaded = _store(path).load()
    assert set(loaded) == {"n5-0001", "n5-0002"}
    assert loaded["n5-0001"].detail == _detail("我")


def test_get_unknown_returns_none(tmp_path: Path) -> None:
    store = _store(tmp_path / "word_details_cache.json")
    assert store.get("n5-0001") is None
    store.put("n5-0001", _detail(), "2025-01-01T00:00:00Z")
    assert store.get("n5-9999") is None


def test_put_empty_id_ignored(tmp_path: Path) -> None:
    store = _store(tmp_path / "word_details_cache.json")
    store.put("", _detail(), "2025-01-01T00:00:00Z")
    assert store.load() == {}


# --------------------------------------------------------------------------- #
# 2. 容错读（缺失 / 空 / 结构损坏 → 备份）
# --------------------------------------------------------------------------- #
def test_missing_file_returns_empty(tmp_path: Path) -> None:
    assert _store(tmp_path / "word_details_cache.json").load() == {}


def test_empty_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "word_details_cache.json"
    _write(path, "")
    assert _store(path).load() == {}


def test_invalid_json_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "word_details_cache.json"
    _write(path, "{ not json ]")
    assert _store(path).load() == {}
    backups = list(path.parent.glob("word_details_cache.json.corrupt-*"))
    assert len(backups) == 1, f"损坏文件应被备份：{backups}"


def test_non_object_root_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "word_details_cache.json"
    _write(path, "[1, 2, 3]")
    assert _store(path).load() == {}
    assert len(list(path.parent.glob("word_details_cache.json.corrupt-*"))) == 1


def test_items_not_object_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "word_details_cache.json"
    _write(path, json.dumps({"version": 1, "items": [1, 2]}))
    assert _store(path).load() == {}
    assert len(list(path.parent.glob("word_details_cache.json.corrupt-*"))) == 1


def test_invalid_items_skipped_valid_kept(tmp_path: Path) -> None:
    path = tmp_path / "word_details_cache.json"
    good = _detail()
    _write(
        path,
        json.dumps(
            {
                "version": C.WORD_DETAILS_CACHE_VERSION,
                "items": {
                    "n5-0001": {"fetched_at": "2025-01-01T00:00:00Z", "detail": good.to_dict()},
                    "n5-0002": {"fetched_at": "2025-01-01T00:00:00Z"},  # 缺 detail
                    "n5-0003": {"detail": good.to_dict()},               # 缺 fetched_at
                    "n5-0004": "not-a-dict",
                },
            }
        ),
    )
    loaded = _store(path).load()
    assert set(loaded) == {"n5-0001"}
    assert loaded["n5-0001"].detail == good


# --------------------------------------------------------------------------- #
# 3. 原子写
# --------------------------------------------------------------------------- #
def test_save_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "word_details_cache.json"
    store = _store(path)
    store.put("n5-0001", _detail(), "2025-01-01T00:00:00Z")
    leftover = list(path.parent.glob("*.tmp")) + list(path.parent.glob("word-details-cache-*"))
    assert leftover == [], f"原子保存残留临时文件：{leftover}"


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "word_details_cache.json"
    store = _store(nested)
    store.put("n5-0001", _detail(), "2025-01-01T00:00:00Z")
    assert nested.exists()


def test_put_overwrites_existing(tmp_path: Path) -> None:
    path = tmp_path / "word_details_cache.json"
    store = _store(path)
    store.put("n5-0001", _detail("我"), "2025-01-01T00:00:00Z")
    store.put("n5-0001", _detail("你"), "2025-01-02T00:00:00Z")
    item = _store(path).load()["n5-0001"]
    assert item.detail.meaning_zh == ("你",)
    assert item.fetched_at == "2025-01-02T00:00:00Z"


# --------------------------------------------------------------------------- #
# 4. WordDetailsCacheItem 序列化
# --------------------------------------------------------------------------- #
def test_cache_item_roundtrip() -> None:
    item = WordDetailsCacheItem(fetched_at="2025-01-01T00:00:00Z", detail=_detail())
    assert WordDetailsCacheItem.from_dict(item.to_dict()) == item


def test_cache_item_from_dict_invalid() -> None:
    assert WordDetailsCacheItem.from_dict(None) is None
    assert WordDetailsCacheItem.from_dict({}) is None
    assert WordDetailsCacheItem.from_dict({"fetched_at": "x"}) is None  # 缺 detail
    assert WordDetailsCacheItem.from_dict({"detail": _detail().to_dict()}) is None  # 缺 fetched_at
    assert WordDetailsCacheItem.from_dict({"fetched_at": "  ", "detail": {}}) is None  # 空时间


# --------------------------------------------------------------------------- #
# 5. 默认路径（隔离 APPDATA）
# --------------------------------------------------------------------------- #
def test_default_path_uses_appdata(isolated_appdata: Path) -> None:
    path = WordDetailsCacheStore.default_path()
    assert path == isolated_appdata / C.CONFIG_DIR_NAME / C.WORD_DETAILS_CACHE_FILENAME
