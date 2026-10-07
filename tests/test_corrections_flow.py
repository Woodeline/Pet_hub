"""工程师自测：词库纠错（覆盖层）—— 加载套用 / 提交 / 撤销 / 快照同步 / 进度保持。

APPDATA 全替身（``monkeypatch.setenv`` + ``paths.word_bank_path``）：
corrections / vocabulary / mastered / daily_log / bank_registry 全部落 tmp_path，
绝不触碰真实 ``%APPDATA%``。

覆盖：
1. 启动套用：预置 corrections.json → ``_load_japanese`` 后词条字段为纠错值。
2. 提交：词库立即生效 + 生词本 / 已掌握快照同步 + 详情缓存按 id 失效。
3. 进度保持：mastered 的 stage / due_at / review_count 原样（纠错≠遗忘）。
4. 重复纠错同字段：``old_value`` 恒为最初原值；撤销还原到最初原值。
5. 覆盖层目标词条缺失（如上游重建 id 变化）：告警跳过，不拖垮词库加载。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import paths
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.corrections_store import CorrectionItem, CorrectionStore

_ISO_T0 = "2025-01-01T00:00:00Z"
_ISO_DUE = "2025-01-03T00:00:00Z"


def _word(i: int, **overrides) -> dict:
    """构造一条合法词条（字段满足 VocabEntry.from_dict 校验）。"""

    data = {
        "id": f"n5-{i:04d}",
        "level": "N5",
        "word": f"語{i}",
        "kana": "かな",
        "translation": "译",
        "meaning": "义",
    }
    data.update(overrides)
    return data


@pytest.fixture()
def ctrl(qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PetAppController:
    """APPDATA 重定向 + 内置词库替身 + 托盘通知 spy。"""

    appdata = tmp_path / "APPDATA"
    appdata.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "jlpt_words.json").write_text(
        json.dumps({"version": 1, "words": [_word(1), _word(2)]}, ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(paths, "word_bank_path", lambda: data_dir / "jlpt_words.json")
    monkeypatch.setattr(paths, "extra_word_bank_path", lambda: appdata / "jlpt_words_extra.json")
    monkeypatch.setattr(paths, "banks_dir", lambda: appdata / "banks")

    controller = PetAppController(qapp, ConfigStore(tmp_path / "cfg" / "config.json"))
    notifications: list[str] = []
    controller._tray.notify = lambda title, message: notifications.append(message)  # type: ignore[method-assign]
    controller._notifications = notifications  # type: ignore[attr-defined]
    return controller


def _reload_store() -> CorrectionStore:
    """按默认路径重开一个纠错 store（验证已落盘）。"""

    store = CorrectionStore(CorrectionStore.default_path())
    store.load()
    return store


# --------------------------------------------------------------------------- #
# 启动套用
# --------------------------------------------------------------------------- #
def test_overlay_applied_on_load(ctrl: PetAppController) -> None:
    """预置纠错记录 → 启动加载后词条字段为纠错值，其余字段不动。"""

    store = CorrectionStore(CorrectionStore.default_path())
    store.load()
    store.upsert(
        CorrectionItem(
            id="n5-0001",
            word="語1",
            field="kana",
            old_value="かな",
            new_value="かな2",
            created_at=_ISO_T0,
        )
    )

    ctrl._load_japanese()

    entry = ctrl._bank.entry_by_id("n5-0001")
    assert entry is not None
    assert entry.kana == "かな2"
    assert (entry.word, entry.translation, entry.meaning) == ("語1", "译", "义")
    assert ctrl._bank.entry_by_id("n5-0002").kana == "かな"


def test_overlay_missing_entry_tolerated(ctrl: PetAppController) -> None:
    """纠错目标词条不在词库（id 失联）：告警跳过，词库加载不受影响。"""

    store = CorrectionStore(CorrectionStore.default_path())
    store.load()
    store.upsert(
        CorrectionItem(
            id="n5-9999", word="幽灵", field="kana", old_value="か", new_value="な"
        )
    )

    ctrl._load_japanese()

    assert not ctrl._bank.is_empty()
    assert ctrl._bank.entry_by_id("n5-0001") is not None


# --------------------------------------------------------------------------- #
# 提交：词库 / 快照 / 缓存 / 进度
# --------------------------------------------------------------------------- #
class _SpyCache:
    """详情缓存替身：只记录 discard 调用（避免构造 WordDetail）。"""

    def __init__(self) -> None:
        self.discarded: list[str] = []

    def discard(self, item_id: str) -> bool:
        self.discarded.append(item_id)
        return True


def test_apply_correction_updates_bank_snapshots_cache(ctrl: PetAppController) -> None:
    """提交纠错：词库生效 + 生词本/已掌握快照同步 + 详情缓存失效 + 通知。"""

    ctrl._load_japanese()
    entry = ctrl._bank.entry_by_id("n5-0001")
    ctrl._vocab.add(entry, _ISO_T0)
    ctrl._mastered.add(entry, _ISO_T0, stage=2, due_at=_ISO_DUE)
    spy = _SpyCache()
    ctrl._detail_cache = spy  # type: ignore[assignment]

    ctrl._on_correction_applied("n5-0001", "語1", "kana", "かな2", "词典读音")

    assert ctrl._bank.entry_by_id("n5-0001").kana == "かな2"
    vocab_item = next(i for i in ctrl._vocab.items() if i.id == "n5-0001")
    assert (vocab_item.kana, vocab_item.added_at) == ("かな2", _ISO_T0)
    mastered_item = ctrl._mastered.get("n5-0001")
    assert mastered_item is not None
    assert mastered_item.kana == "かな2"
    assert spy.discarded == ["n5-0001"]
    assert any("已记录纠错" in m for m in ctrl._notifications)


def test_apply_correction_keeps_srs_progress(ctrl: PetAppController) -> None:
    """纠错是数据修正而非遗忘：stage / due_at / review_count 原样保留。"""

    ctrl._load_japanese()
    entry = ctrl._bank.entry_by_id("n5-0001")
    ctrl._mastered.add(entry, _ISO_T0, stage=2, due_at=_ISO_DUE)

    ctrl._on_correction_applied("n5-0001", "語1", "kana", "かな2", "")

    item = ctrl._mastered.get("n5-0001")
    assert item is not None
    assert (item.stage, item.due_at, item.review_count) == (2, _ISO_DUE, 0)
    assert item.last_review_at == _ISO_T0


def test_apply_persists_record_with_original_old_value(ctrl: PetAppController) -> None:
    """提交后落盘可重载：old_value = 最初原值、备注与时间注入。"""

    ctrl._load_japanese()
    ctrl._now_iso = lambda: _ISO_T0  # type: ignore[method-assign]

    ctrl._on_correction_applied("n5-0001", "語1", "kana", "かな2", "词典读音")

    reloaded = _reload_store()
    assert reloaded.count() == 1
    rec = reloaded.items()[0]
    assert (rec.id, rec.field, rec.old_value, rec.new_value) == (
        "n5-0001",
        "kana",
        "かな",
        "かな2",
    )
    assert rec.note == "词典读音"
    assert rec.created_at == _ISO_T0


def test_reapply_same_field_keeps_original_old_value(ctrl: PetAppController) -> None:
    """同字段两次纠错（かな→かな2→かな3）：单条记录、old_value 恒为最初原值。"""

    ctrl._load_japanese()
    ctrl._on_correction_applied("n5-0001", "語1", "kana", "かな2", "")
    ctrl._on_correction_applied("n5-0001", "語1", "kana", "かな3", "")

    assert ctrl._bank.entry_by_id("n5-0001").kana == "かな3"
    reloaded = _reload_store()
    assert reloaded.count() == 1
    rec = reloaded.items()[0]
    assert (rec.old_value, rec.new_value) == ("かな", "かな3")


def test_apply_unknown_word_notifies_failure(ctrl: PetAppController) -> None:
    """词条已不在词库：托盘失败通知，不落盘、不重建。"""

    ctrl._load_japanese()
    ctrl._on_correction_applied("n5-9999", "幽灵", "kana", "かな2", "")

    assert any("纠错失败" in m for m in ctrl._notifications)
    assert _reload_store().count() == 0


# --------------------------------------------------------------------------- #
# 撤销
# --------------------------------------------------------------------------- #
def test_undo_restores_original(ctrl: PetAppController) -> None:
    """撤销纠错：词库 / 生词本 / 已掌握快照还原最初原值，记录删除。"""

    ctrl._load_japanese()
    entry = ctrl._bank.entry_by_id("n5-0001")
    ctrl._vocab.add(entry, _ISO_T0)
    ctrl._mastered.add(entry, _ISO_T0, stage=1, due_at=_ISO_DUE)
    ctrl._on_correction_applied("n5-0001", "語1", "kana", "かな2", "")

    ctrl._on_correction_undo("n5-0001", "kana")

    assert ctrl._bank.entry_by_id("n5-0001").kana == "かな"
    assert next(i for i in ctrl._vocab.items() if i.id == "n5-0001").kana == "かな"
    assert ctrl._mastered.get("n5-0001").kana == "かな"
    assert _reload_store().count() == 0
    assert any("已撤销纠错" in m for m in ctrl._notifications)


def test_undo_after_double_correction_reverts_to_original(ctrl: PetAppController) -> None:
    """两次纠错后撤销：一步还原到最初原值（而非中间值）。"""

    ctrl._load_japanese()
    ctrl._on_correction_applied("n5-0001", "語1", "kana", "かな2", "")
    ctrl._on_correction_applied("n5-0001", "語1", "kana", "かな3", "")

    ctrl._on_correction_undo("n5-0001", "kana")

    assert ctrl._bank.entry_by_id("n5-0001").kana == "かな"


def test_undo_without_record_is_noop(ctrl: PetAppController) -> None:
    """撤销不存在的纠错记录：无通知、无异常。"""

    ctrl._load_japanese()
    notifications_before = list(ctrl._notifications)

    ctrl._on_correction_undo("n5-0001", "kana")

    assert ctrl._notifications == notifications_before


# --------------------------------------------------------------------------- #
# 快照同步的其它字段
# --------------------------------------------------------------------------- #
def test_translation_correction_syncs_snapshots(ctrl: PetAppController) -> None:
    """翻译纠错同样同步生词本 / 已掌握快照（展示一致）。"""

    ctrl._load_japanese()
    entry = ctrl._bank.entry_by_id("n5-0001")
    ctrl._vocab.add(entry, _ISO_T0)
    ctrl._mastered.add(entry, _ISO_T0, stage=0, due_at=_ISO_DUE)

    ctrl._on_correction_applied("n5-0001", "語1", "translation", "翻译", "")

    assert ctrl._bank.entry_by_id("n5-0001").translation == "翻译"
    assert next(i for i in ctrl._vocab.items() if i.id == "n5-0001").translation == "翻译"
    assert ctrl._mastered.get("n5-0001").translation == "翻译"
