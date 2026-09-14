"""生词本持久化 单测（JP-08/09/10/16）：去重 / 原子写 / 损坏备份 / 逐字段容错。

全部为 ``core`` 纯逻辑测试，**不需要 Qt**。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.vocab_store import VocabItem, VocabStore
from desktop_pet.core.vocabulary import VocabEntry


def _entry(i: int, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}",
        kana="かな", translation="译", meaning="义",
    )


@pytest.fixture()
def store(tmp_path: Path) -> VocabStore:
    return VocabStore(tmp_path / "desktop-pet" / "vocabulary.json")


# --------------------------------------------------------------------------- #
# 1. 默认路径
# --------------------------------------------------------------------------- #
def test_default_path_uses_appdata(isolated_appdata: Path) -> None:
    path = VocabStore.default_path()
    assert path == isolated_appdata / C.CONFIG_DIR_NAME / C.VOCAB_FILE_NAME


def test_default_path_without_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    path = VocabStore.default_path()
    assert path.name == C.VOCAB_FILE_NAME
    assert Path.home() in path.parents


# --------------------------------------------------------------------------- #
# 2. add 去重 / remove / clear
# --------------------------------------------------------------------------- #
def test_load_missing_file_returns_empty(store: VocabStore) -> None:
    assert store.load() == []
    assert store.count() == 0


def test_add_and_dedup(store: VocabStore) -> None:
    assert store.add(_entry(1), "2025-01-01T00:00:00Z") is True
    assert store.add(_entry(1), "2025-01-02T00:00:00Z") is False  # 已存在
    assert store.count() == 1
    assert store.contains("n5-0001")


def test_add_none_returns_false(store: VocabStore) -> None:
    assert store.add(None, "t") is False  # type: ignore[arg-type]


def test_add_persists_to_disk(store: VocabStore) -> None:
    store.add(_entry(1), "2025-01-01T00:00:00Z")
    reloaded = VocabStore(store.path)
    reloaded.load()
    assert reloaded.count() == 1
    assert reloaded.items()[0].word == "語1"


def test_remove(store: VocabStore) -> None:
    store.add(_entry(1), "t1")
    store.add(_entry(2), "t2")
    assert store.remove("n5-0001") is True
    assert store.remove("n5-0001") is False  # 已删除
    assert store.count() == 1


def test_clear(store: VocabStore) -> None:
    store.add(_entry(1), "t1")
    store.clear()
    assert store.count() == 0
    reloaded = VocabStore(store.path)
    reloaded.load()
    assert reloaded.count() == 0


def test_items_preserve_insertion_order(store: VocabStore) -> None:
    store.add(_entry(1), "t1")
    store.add(_entry(2), "t2")
    assert [i.id for i in store.items()] == ["n5-0001", "n5-0002"]


# --------------------------------------------------------------------------- #
# 3. VocabItem.from_dict 容错
# --------------------------------------------------------------------------- #
def test_item_from_entry_and_dict_roundtrip() -> None:
    item = VocabItem.from_entry(_entry(1), "2025-01-01T00:00:00Z")
    assert item.added_at == "2025-01-01T00:00:00Z"
    assert VocabItem.from_dict(item.to_dict()) == item


@pytest.mark.parametrize(
    "bad",
    [
        "x",
        None,
        [],
        {"id": "n5-0001"},                       # 缺字段
        {"id": "", "level": "N5", "word": "w", "kana": "k", "translation": "t", "meaning": "m", "added_at": "a"},
    ],
)
def test_item_from_dict_rejects_invalid(bad) -> None:
    assert VocabItem.from_dict(bad) is None


# --------------------------------------------------------------------------- #
# 4. 原子写
# --------------------------------------------------------------------------- #
def test_save_creates_parent_and_no_temp_leftover(store: VocabStore) -> None:
    store.add(_entry(1), "t1")
    leftovers = list(store.path.parent.glob("*.tmp")) + list(store.path.parent.glob("vocab-*"))
    assert leftovers == [], f"原子保存残留临时文件：{leftovers}"
    assert store.path.exists()


def test_save_never_raises_on_bad_path(tmp_path: Path) -> None:
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    bad = VocabStore(blocker / "sub" / "vocabulary.json")
    bad.add(_entry(1), "t1")  # 不应抛异常


# --------------------------------------------------------------------------- #
# 5. 损坏处理：备份而非静默清空
# --------------------------------------------------------------------------- #
def test_corrupt_json_is_backed_up_not_cleared(store: VocabStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    corrupt_text = "{ this is not json ]"
    store.path.write_text(corrupt_text, encoding="utf-8")

    assert store.load() == []
    assert store.count() == 0

    backups = list(store.path.parent.glob(f"{C.VOCAB_FILE_NAME}.corrupt-*"))
    assert backups, "损坏文件未被备份（数据可能被静默清空）"
    assert backups[0].read_text(encoding="utf-8") == corrupt_text, "备份内容应保留原始数据"
    assert not store.path.exists(), "损坏文件应被 os.replace 移走，而非原地清空"


def test_items_not_list_is_backed_up(store: VocabStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(json.dumps({"version": 1, "items": "oops"}), encoding="utf-8")
    assert store.load() == []
    assert list(store.path.parent.glob(f"{C.VOCAB_FILE_NAME}.corrupt-*"))


def test_root_not_object_is_backed_up(store: VocabStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("[1, 2, 3]", encoding="utf-8")
    assert store.load() == []
    assert list(store.path.parent.glob(f"{C.VOCAB_FILE_NAME}.corrupt-*"))


def test_per_item_tolerance_keeps_valid(store: VocabStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    VocabItem.from_entry(_entry(1), "t1").to_dict(),
                    {"id": "broken"},  # 非法 → 跳过
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    items = store.load()
    assert len(items) == 1
    assert items[0].id == "n5-0001"
    # 逐条容错不算「损坏」，不应产生备份
    assert not list(store.path.parent.glob(f"{C.VOCAB_FILE_NAME}.corrupt-*"))


def test_empty_file_is_not_treated_as_corrupt(store: VocabStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("   \n", encoding="utf-8")
    assert store.load() == []
    assert not list(store.path.parent.glob(f"{C.VOCAB_FILE_NAME}.corrupt-*"))


def test_double_corruption_does_not_overwrite_backup(store: VocabStore) -> None:
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("bad one", encoding="utf-8")
    store.load()
    store.path.write_text("bad two", encoding="utf-8")
    store.load()
    backups = list(store.path.parent.glob(f"{C.VOCAB_FILE_NAME}.corrupt-*"))
    assert len(backups) >= 2, "第二次损坏应生成新备份，不覆盖旧备份"
