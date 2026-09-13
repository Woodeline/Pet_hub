"""学习进度持久化单测（JP-18：每日配额 + 已记住集合）。

**隔离要求**：所有读写都使用 ``tmp_path``，绝不触碰真实 ``%APPDATA%``。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.jp_state import JpStateStore

TODAY = "2026-09-13"
TOMORROW = "2026-09-14"


# --------------------------------------------------------------------------- #
# 1. 加载容错
# --------------------------------------------------------------------------- #
def test_load_missing_file_starts_empty(tmp_path: Path) -> None:
    store = JpStateStore(tmp_path / "jp_state.json")
    store.load(TODAY)
    assert store.date() == TODAY
    assert store.shown_ids() == []
    assert store.learned_ids() == set()


def test_load_corrupt_file_backs_up_then_empty(tmp_path: Path) -> None:
    path = tmp_path / "jp_state.json"
    path.write_text("{ broken json ]", encoding="utf-8")
    store = JpStateStore(path)
    store.load(TODAY)
    assert store.shown_ids() == []
    backups = list(tmp_path.glob("jp_state.json.corrupt-*"))
    assert len(backups) == 1, "损坏文件未被备份"


def test_load_non_object_root_backs_up(tmp_path: Path) -> None:
    path = tmp_path / "jp_state.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    store = JpStateStore(path)
    store.load(TODAY)
    assert store.shown_ids() == []
    assert len(list(tmp_path.glob("jp_state.json.corrupt-*"))) == 1


def test_load_never_raises_on_directory_path(tmp_path: Path) -> None:
    directory = tmp_path / "jp_state.json"
    directory.mkdir()
    store = JpStateStore(directory)
    store.load(TODAY)  # 不应抛异常
    assert store.date() == TODAY


# --------------------------------------------------------------------------- #
# 2. 记录与去重
# --------------------------------------------------------------------------- #
def test_record_shown_dedupes_and_persists(tmp_path: Path) -> None:
    path = tmp_path / "jp_state.json"
    store = JpStateStore(path)
    store.load(TODAY)
    store.record_shown("n5-0001", TODAY)
    store.record_shown("n5-0001", TODAY)  # 重复展示不去重前会双计
    store.record_shown("n5-0002", TODAY)
    assert store.shown_ids() == ["n5-0001", "n5-0002"]

    again = JpStateStore(path)
    again.load(TODAY)
    assert again.shown_ids() == ["n5-0001", "n5-0002"], "展示进度未持久化"


def test_record_learned_persists_across_rollover(tmp_path: Path) -> None:
    """「记住了」跨天永久保留；当日展示进度跨天清零。"""

    path = tmp_path / "jp_state.json"
    store = JpStateStore(path)
    store.load(TODAY)
    store.record_shown("n5-0001", TODAY)
    store.record_learned("n5-0001", TODAY)

    # 第二天加载：learned 保留，shown 清零
    next_day = JpStateStore(path)
    next_day.load(TOMORROW)
    assert next_day.learned_ids() == {"n5-0001"}
    assert next_day.shown_ids() == []
    assert next_day.date() == TOMORROW


def test_record_shown_after_rollover_uses_new_date(tmp_path: Path) -> None:
    path = tmp_path / "jp_state.json"
    store = JpStateStore(path)
    store.load(TODAY)
    store.record_shown("n5-0001", TODAY)
    store.record_shown("n5-0009", TOMORROW)  # 跨天记录触发 rollover
    assert store.date() == TOMORROW
    assert store.shown_ids() == ["n5-0009"]


def test_record_skips_blank_id(tmp_path: Path) -> None:
    store = JpStateStore(tmp_path / "jp_state.json")
    store.load(TODAY)
    store.record_shown("", TODAY)
    store.record_learned("  ", TODAY)
    assert store.shown_ids() == []
    assert store.learned_ids() == set()


# --------------------------------------------------------------------------- #
# 3. 文件格式与原子保存
# --------------------------------------------------------------------------- #
def test_saved_json_structure(tmp_path: Path) -> None:
    path = tmp_path / "jp_state.json"
    store = JpStateStore(path)
    store.load(TODAY)
    store.record_shown("n5-0001", TODAY)
    store.record_learned("n5-0002", TODAY)

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["version"] == C.JP_STATE_VERSION == 1
    assert data["date"] == TODAY
    assert data["shown_ids"] == ["n5-0001"]
    assert "n5-0002" in data["learned_ids"]


def test_save_leaves_no_temp_files(tmp_path: Path) -> None:
    path = tmp_path / "jp_state.json"
    store = JpStateStore(path)
    store.load(TODAY)
    store.record_shown("n5-0001", TODAY)
    leftover = list(tmp_path.glob("*.tmp")) + list(tmp_path.glob("jpstate-*"))
    assert leftover == [], f"原子保存残留临时文件：{leftover}"


# --------------------------------------------------------------------------- #
# 4. 默认路径（隔离 APPDATA）
# --------------------------------------------------------------------------- #
def test_default_path_uses_appdata(isolated_appdata: Path) -> None:
    path = JpStateStore.default_path()
    assert path == isolated_appdata / C.CONFIG_DIR_NAME / C.JP_STATE_FILE_NAME


def test_default_path_without_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    path = JpStateStore.default_path()
    assert path.name == C.JP_STATE_FILE_NAME
    assert Path.home() in path.parents
