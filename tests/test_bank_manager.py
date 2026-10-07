"""工程师自测：多词库管理 controller 侧 —— 迁移 / 导入 / 启停 / 删除 / 合并重建。

paths 全替身：内置词库、旧外置词库、banks 目录全部落 tmp_path
（绝不触碰真实 ``%APPDATA%``——迁移与登记测试直接读用户数据的教训）。

覆盖：
1. 旧外置词库幂等迁移进 banks/（原文件保留）。
2. 导入：登记 + 复制 + 合并；解析失败拒绝且不登记。
3. 启停：停用词库的词退出学习池；文件保留。
4. 删除：登记与文件一并移除。
5. 合并顺序：后导入覆盖同 id（added_at 升序合并）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import paths
from desktop_pet.core.bank_registry import BankRegistryStore
from desktop_pet.core.config import ConfigStore


def _word(i: int, word: str | None = None) -> dict:
    """构造一条合法词条（字段满足 VocabEntry.from_dict 校验）。"""

    return {
        "id": f"n5-{i:04d}",
        "level": "N5",
        "word": word or f"語{i}",
        "kana": "かな",
        "translation": "译",
        "meaning": "义",
    }


def _write_bank(path: Path, words: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"version": 1, "words": words}, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def ctrl(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PetAppController:
    """paths 全替身 + 最小 controller + 托盘通知 spy。"""

    data_dir = tmp_path / "data"
    appdata = tmp_path / "appdata"
    data_dir.mkdir(parents=True)
    appdata.mkdir()
    # 内置词库：2 词（n5-0001 / n5-0002）
    _write_bank(data_dir / "jlpt_words.json", [_word(1), _word(2)])

    monkeypatch.setattr(paths, "word_bank_path", lambda: data_dir / "jlpt_words.json")
    monkeypatch.setattr(paths, "extra_word_bank_path", lambda: appdata / "jlpt_words_extra.json")
    monkeypatch.setattr(paths, "banks_dir", lambda: appdata / "banks")
    monkeypatch.setattr(
        BankRegistryStore, "default_path", staticmethod(lambda: appdata / "bank_registry.json")
    )
    monkeypatch.setattr(BankRegistryStore, "banks_dir", staticmethod(lambda: appdata / "banks"))

    controller = PetAppController(qapp, ConfigStore(tmp_path / "cfg" / "config.json"))
    notifications: list[str] = []

    def _spy(title: str, message: str) -> None:
        notifications.append(message)

    controller._tray.notify = _spy  # type: ignore[method-assign]
    controller._notifications = notifications  # type: ignore[attr-defined]
    return controller


def _banks_dir(ctrl: PetAppController) -> Path:
    return ctrl._bank_registry.banks_dir()


# --------------------------------------------------------------------------- #
# 旧外置词库迁移
# --------------------------------------------------------------------------- #
def test_legacy_extra_bank_migrated_on_load(ctrl: PetAppController) -> None:
    """旧外置词库存在 + 登记表空 → 迁移进 banks/ 并登记，词可查。"""

    legacy = paths.extra_word_bank_path()
    _write_bank(legacy, [_word(3), _word(4)])

    ctrl._load_japanese()

    records = ctrl._bank_registry.records()
    assert len(records) == 1
    assert (_banks_dir(ctrl) / records[0].file).is_file()
    assert legacy.exists(), "原文件保留作备份"
    assert ctrl._bank.entry_by_id("n5-0003") is not None
    assert any("迁移" in msg for msg in ctrl._notifications)


def test_legacy_migration_is_idempotent(ctrl: PetAppController) -> None:
    """二次加载：登记表已有记录，不再迁移（不产生重复库）。"""

    _write_bank(paths.extra_word_bank_path(), [_word(3)])
    ctrl._load_japanese()
    ctrl._load_japanese()
    assert len(ctrl._bank_registry.records()) == 1


def test_migration_skipped_when_registry_has_banks(ctrl: PetAppController) -> None:
    """登记表非空（已手动导入过）：旧文件不迁移。"""

    _write_bank(paths.extra_word_bank_path(), [_word(3)])
    ctrl._load_japanese()
    # 手动导入第二个库
    src = _write_bank(ctrl._bank_registry.banks_dir().parent / "src2.json", [_word(5)])
    ctrl._on_banks_import([str(src)])
    assert len(ctrl._bank_registry.records()) == 2


def test_migration_ignores_invalid_legacy_file(ctrl: PetAppController) -> None:
    """旧文件 JSON 损坏：迁移跳过（告警不崩溃），仅用内置库启动。"""

    legacy = paths.extra_word_bank_path()
    legacy.parent.mkdir(parents=True, exist_ok=True)
    legacy.write_text("{broken", encoding="utf-8")
    ctrl._load_japanese()
    assert ctrl._bank_registry.records() == ()
    assert ctrl._bank.entry_by_id("n5-0001") is not None


# --------------------------------------------------------------------------- #
# 导入
# --------------------------------------------------------------------------- #
def test_import_registers_copies_and_merges(ctrl: PetAppController) -> None:
    """导入：登记 + 复制入 banks/ + 合并进运行中词库。"""

    ctrl._load_japanese()
    src = _write_bank(
        ctrl._bank_registry.banks_dir().parent / "extra.json",
        [_word(3), _word(4), _word(5)],
    )

    ctrl._on_banks_import([str(src)])

    records = ctrl._bank_registry.records()
    assert len(records) == 1
    assert (_banks_dir(ctrl) / records[0].file).is_file()
    assert ctrl._bank.entry_by_id("n5-0005") is not None
    assert ctrl._bank.size() == 5


def test_import_parse_error_rejected(ctrl: PetAppController) -> None:
    """解析失败：通知原因、不登记、词库不变。"""

    ctrl._load_japanese()
    bad = ctrl._bank_registry.banks_dir().parent / "bad.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{broken", encoding="utf-8")

    ctrl._on_banks_import([str(bad)])

    assert ctrl._bank_registry.records() == ()
    assert any("失败" in msg for msg in ctrl._notifications)
    assert ctrl._bank.size() == 2


# --------------------------------------------------------------------------- #
# 启停 / 删除
# --------------------------------------------------------------------------- #
def _import_one(ctrl: PetAppController, word_id: int) -> str:
    src = _write_bank(
        ctrl._bank_registry.banks_dir().parent / f"b{word_id}.json", [_word(word_id)]
    )
    ctrl._on_banks_import([str(src)])
    return ctrl._bank_registry.records()[-1].id


def test_toggle_disabled_removes_words_from_pool(ctrl: PetAppController) -> None:
    """停用：该库的词退出学习池（文件保留）；重新启用恢复。"""

    ctrl._load_japanese()
    bank_id = _import_one(ctrl, 7)
    assert ctrl._bank.entry_by_id("n5-0007") is not None

    ctrl._on_bank_toggle(bank_id, False)
    assert ctrl._bank.entry_by_id("n5-0007") is None

    bank_file = next((_banks_dir(ctrl) / r.file for r in ctrl._bank_registry.records() if r.id == bank_id))
    assert bank_file.exists(), "文件保留"

    ctrl._on_bank_toggle(bank_id, True)
    assert ctrl._bank.entry_by_id("n5-0007") is not None


def test_delete_removes_record_and_file(ctrl: PetAppController) -> None:
    """删除：登记移除 + 文件删除 + 词退出学习池。"""

    ctrl._load_japanese()
    bank_id = _import_one(ctrl, 8)
    bank_file = _banks_dir(ctrl) / ctrl._bank_registry.get(bank_id).file
    assert bank_file.exists()

    ctrl._on_bank_delete(bank_id)
    assert ctrl._bank_registry.get(bank_id) is None
    assert not bank_file.exists()
    assert ctrl._bank.entry_by_id("n5-0008") is None


# --------------------------------------------------------------------------- #
# 合并顺序
# --------------------------------------------------------------------------- #
def test_later_bank_overrides_same_id(ctrl: PetAppController) -> None:
    """同 id 词条：后导入的库（added_at 更晚）覆盖先导入的。"""

    ctrl._load_japanese()
    # 注入固定 ISO 使 added_at 严格递增
    isos = iter([
        "2025-01-01T00:00:00Z",
        "2025-01-02T00:00:00Z",
        "2025-01-03T00:00:00Z",
    ])
    ctrl._now_iso = lambda: next(isos)  # type: ignore[method-assign]

    first = _write_bank(
        ctrl._bank_registry.banks_dir().parent / "first.json",
        [_word(9, word="旧译")],
    )
    second = _write_bank(
        ctrl._bank_registry.banks_dir().parent / "second.json",
        [_word(9, word="新译")],
    )
    ctrl._on_banks_import([str(first)])
    ctrl._on_banks_import([str(second)])

    assert ctrl._bank.entry_by_id("n5-0009").word == "新译"
