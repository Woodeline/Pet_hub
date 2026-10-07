"""工程师自测：core.bank_registry —— 多词库登记表（round-trip / 排序 / 容错）。

覆盖：
1. add：id / 文件名生成（``<id>.json``）、同秒同名导入去重碰撞、落盘。
2. records：按 added_at 升序（= 合并顺序）；get / set_enabled / remove。
3. 容错：损坏文件先备份再空表继续；非法记录与重复 id 跳过；路径逃逸文件名拒收。
4. 空表 / 文件缺失。

core 零时钟约定：added_at 由测试注入字符串。
"""

from __future__ import annotations

import json
from pathlib import Path

from desktop_pet.core import constants as C
from desktop_pet.core.bank_registry import BankRegistryStore

_T0 = "2025-01-01T00:00:00Z"
_T1 = "2025-01-02T00:00:00Z"
_T2 = "2025-01-03T00:00:00Z"


def _store(tmp_path: Path) -> BankRegistryStore:
    store = BankRegistryStore(tmp_path / "bank_registry.json")
    store.load()
    return store


# --------------------------------------------------------------------------- #
# add / id 生成
# --------------------------------------------------------------------------- #
def test_add_generates_id_and_file(tmp_path: Path) -> None:
    """add：id 形如 bk-<10位>、文件名 = <id>.json、enabled 默认 True。"""

    store = _store(tmp_path)
    record = store.add("OpenJLPT N5", _T0)
    assert record.id.startswith("bk-") and len(record.id) == 13
    assert record.file == f"{record.id}.json"
    assert record.enabled is True
    assert record.name == "OpenJLPT N5"
    assert store.get(record.id) is record


def test_add_duplicate_name_same_time_no_collision(tmp_path: Path) -> None:
    """同秒同名导入两次：id 去重碰撞处理，两条记录共存。"""

    store = _store(tmp_path)
    a = store.add("同名", _T0)
    b = store.add("同名", _T0)
    assert a.id != b.id
    assert len(store.records()) == 2


def test_add_name_collapsed(tmp_path: Path) -> None:
    """展示名空白折叠；纯空白回落「导入词库」。"""

    store = _store(tmp_path)
    assert store.add("  A   B  ", _T0).name == "A B"
    assert store.add("   ", _T0).name == "导入词库"


# --------------------------------------------------------------------------- #
# 排序与变更
# --------------------------------------------------------------------------- #
def test_records_sorted_by_added_at(tmp_path: Path) -> None:
    """records 按 added_at 升序（先导入先合并、后被覆盖），与插入顺序无关。"""

    store = _store(tmp_path)
    c = store.add("C", _T2)
    a = store.add("A", _T0)
    b = store.add("B", _T1)
    assert [r.id for r in store.records()] == [a.id, b.id, c.id]


def test_set_enabled_roundtrip(tmp_path: Path) -> None:
    """启停切换落盘可读回；未知 id 返回 False。"""

    store = _store(tmp_path)
    record = store.add("X", _T0)
    assert store.set_enabled(record.id, False) is True
    reloaded = BankRegistryStore(tmp_path / "bank_registry.json")
    reloaded.load()
    assert reloaded.get(record.id).enabled is False
    assert store.set_enabled("bk-nothing", True) is False


def test_remove_returns_record(tmp_path: Path) -> None:
    """remove 返回被移除记录并落盘；再取为 None。"""

    store = _store(tmp_path)
    record = store.add("Y", _T0)
    removed = store.remove(record.id)
    assert removed is not None and removed.id == record.id
    assert store.get(record.id) is None
    assert store.records() == ()


# --------------------------------------------------------------------------- #
# 持久化 / 容错
# --------------------------------------------------------------------------- #
def test_save_load_roundtrip(tmp_path: Path) -> None:
    """save → 全新 store load：记录逐字段还原。"""

    store = _store(tmp_path)
    store.add("甲", _T0)
    store.add("乙", _T1)
    reloaded = BankRegistryStore(tmp_path / "bank_registry.json")
    records = reloaded.load()
    assert len(records) == 2
    assert [r.name for r in records] == ["甲", "乙"]
    assert all(r.file == f"{r.id}.json" for r in records)


def test_load_missing_file_returns_empty(tmp_path: Path) -> None:
    """文件缺失：空表启动。"""

    assert BankRegistryStore(tmp_path / "nope.json").load() == ()


def test_load_corrupt_file_backed_up(tmp_path: Path) -> None:
    """损坏文件：先备份为 .corrupt-* 再以空表继续（绝不静默清空）。"""

    path = tmp_path / "bank_registry.json"
    path.write_text("{broken json", encoding="utf-8")
    store = BankRegistryStore(path)
    assert store.load() == ()
    backups = list(tmp_path.glob("bank_registry.json.corrupt-*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "{broken json"


def test_load_skips_invalid_and_duplicate_entries(tmp_path: Path) -> None:
    """非法记录 / 重复 id：跳过；路径逃逸文件名拒收。"""

    path = tmp_path / "bank_registry.json"
    payload = {
        "version": C.BANK_REGISTRY_VERSION,
        "banks": [
            {"id": "bk-aaa", "name": "好库", "file": "bk-aaa.json", "enabled": True, "added_at": _T0},
            {"id": "bk-bad", "name": "", "file": "bk-bad.json", "enabled": True, "added_at": _T1},
            {"id": "bk-aaa", "name": "重复", "file": "bk-aaa.json", "enabled": True, "added_at": _T2},
            {"id": "bk-esc", "name": "逃逸", "file": "../evil.json", "enabled": True, "added_at": _T2},
            {"id": "bk-eb", "name": "非布尔", "file": "bk-eb.json", "enabled": "yes", "added_at": _T2},
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    records = BankRegistryStore(path).load()
    assert [r.id for r in records] == ["bk-aaa"]
