"""工程师自测：词库纠错覆盖层 store —— round-trip / upsert / 撤销 / 损坏容错。

覆盖：
1. round-trip：upsert → 重新加载 → frozen dataclass 全字段相等（JSON 往返保真）。
2. upsert 语义：同 ``(id, field)`` 覆盖替换（不追加重复）；不同字段并存。
3. ``remove``：返回被删记录（撤销还原用）；不存在返回 ``None``。
4. ``from_dict`` 容错：字段名越界 / 必填缺失 → 跳过；``note`` / ``created_at`` 可选。
5. 损坏文件：先 ``.corrupt-*`` 留档再以空记录启动（绝不静默清空）。

遵循项目测试隔离约定：数据落 tmp_path，core 层零时钟（ISO 字符串由测试注入）。
"""

from __future__ import annotations

from pathlib import Path

from desktop_pet.core import constants as C
from desktop_pet.core.corrections_store import CorrectionItem, CorrectionStore

_ISO_T0 = "2025-01-01T00:00:00Z"


def _item(
    item_id: str = "n5-0001",
    field: str = "kana",
    old: str = "かな",
    new: str = "かな2",
) -> CorrectionItem:
    """构造一条测试纠错记录。"""

    return CorrectionItem(
        id=item_id,
        word="語",
        field=field,
        old_value=old,
        new_value=new,
        note="测试",
        created_at=_ISO_T0,
    )


def _store(tmp_path: Path, name: str = "corrections.json") -> CorrectionStore:
    store = CorrectionStore(tmp_path / name)
    store.load()
    return store


# --------------------------------------------------------------------------- #
# round-trip / upsert
# --------------------------------------------------------------------------- #
def test_upsert_roundtrip(tmp_path: Path) -> None:
    """upsert → 新实例重载 → frozen dataclass 全字段相等。"""

    store = _store(tmp_path)
    store.upsert(_item())

    reloaded = _store(tmp_path)
    items = reloaded.items()
    assert len(items) == 1
    assert items[0] == _item()
    assert items[0].created_at == _ISO_T0


def test_upsert_same_id_field_replaces(tmp_path: Path) -> None:
    """同 ``(id, field)`` 再次纠错：覆盖替换而非追加（记录数不变）。"""

    store = _store(tmp_path)
    store.upsert(_item(new="かな2"))
    store.upsert(_item(new="かな3"))

    items = store.items()
    assert len(items) == 1
    assert items[0].new_value == "かな3"


def test_upsert_different_fields_coexist(tmp_path: Path) -> None:
    """同词条不同字段并存：读音与翻译两条独立记录。"""

    store = _store(tmp_path)
    store.upsert(_item(field="kana"))
    store.upsert(_item(field="translation", old="译", new="翻译"))

    assert store.count() == 2
    assert len(store.items_for("n5-0001")) == 2
    assert store.items_for("n5-0002") == []


def test_remove_returns_removed_record(tmp_path: Path) -> None:
    """remove 返回被删记录（供按 ``old_value`` 还原）；不存在返回 None。"""

    store = _store(tmp_path)
    store.upsert(_item())

    removed = store.remove("n5-0001", "kana")
    assert removed == _item()
    assert store.count() == 0
    assert store.remove("n5-0001", "kana") is None


# --------------------------------------------------------------------------- #
# 容错读
# --------------------------------------------------------------------------- #
def test_from_dict_rejects_unknown_field(tmp_path: Path) -> None:
    """字段名越界（不在 ``C.CORRECTION_FIELDS``）的记录跳过，合法记录保留。"""

    path = tmp_path / "corrections.json"
    path.write_text(
        '{"version": 1, "items": ['
        '{"id": "n5-0001", "word": "語", "field": "romaji", "old_value": "a", "new_value": "b"},'
        '{"id": "n5-0002", "word": "語", "field": "word", "old_value": "旧", "new_value": "新"}'
        "]}",
        encoding="utf-8",
    )
    store = _store(tmp_path)
    assert store.count() == 1
    assert store.items()[0].id == "n5-0002"


def test_from_dict_optional_fields_default_empty(tmp_path: Path) -> None:
    """``note`` / ``created_at`` 缺失 → 空串缺省（不拒收）。"""

    path = tmp_path / "corrections.json"
    path.write_text(
        '{"version": 1, "items": ['
        '{"id": "n5-0001", "word": "語", "field": "kana", "old_value": "かな", "new_value": "かな2"}'
        "]}",
        encoding="utf-8",
    )
    store = _store(tmp_path)
    assert store.count() == 1
    assert store.items()[0].note == ""
    assert store.items()[0].created_at == ""


def test_corrupt_file_backed_up_then_empty(tmp_path: Path) -> None:
    """损坏文件：先备份为 ``.corrupt-*`` 再以空记录启动。"""

    path = tmp_path / "corrections.json"
    path.write_text("{broken", encoding="utf-8")

    store = _store(tmp_path)
    assert store.count() == 0
    backups = list(path.parent.glob("corrections.json.corrupt-*"))
    assert len(backups) == 1


def test_file_format_version_pinned(tmp_path: Path) -> None:
    """落盘格式：根对象带 ``version``（= ``C.CORRECTIONS_VERSION``）+ ``items`` 数组。"""

    store = _store(tmp_path)
    store.upsert(_item())
    raw = (tmp_path / "corrections.json").read_text(encoding="utf-8")
    assert f'"version": {C.CORRECTIONS_VERSION}' in raw
    assert '"items"' in raw
