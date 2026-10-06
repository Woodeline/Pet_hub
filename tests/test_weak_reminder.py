"""工程师自测：错题本每日一次提醒 + 抽取加权接线（controller 侧）。

覆盖：
1. 排期制提醒：启动/跨日后随机延迟到点才检查；当日只提醒一次。
2. 开关链：日语学习关 / weak_review_enabled 关 / 当日已提醒 → 不提醒。
3. 无易错词：到点后当日不再重试（避免每帧空转）。
4. 抽取接线：_show_word_bubble 把易错词 TopN 作为 boost_ids 传给 picker。
5. 遗忘处置置脏标记：lapse 后缓存重算。

遵循项目测试隔离约定（配置 / 数据落 tmp_path，墙钟注入替身）。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker

_DAY: str = "2025-01-01"
_ISO: str = "2025-01-01T00:00:00Z"


def _entry(i: int, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}",
        level=level,
        word=f"語{i}",
        kana="かな",
        translation="译",
        meaning="义",
    )


def _lapse_log_entry(word_id: int) -> DailyLogEntry:
    return DailyLogEntry(
        id=f"n5-{word_id:04d}",
        level="N5",
        word=f"語{word_id}",
        kana="かな",
        translation="译",
        shown_at=f"{_DAY}T00:00:00Z",
        status="review_lapsed",
    )


@pytest.fixture()
def ctrl(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """构造最小 controller（同 test_review_scheduler 范式）。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.jp_enabled = True
    ctrl._cfg.bubble_enabled = True
    ctrl._cfg.jp_level = "N5"
    ctrl._cfg.jp_daily_limit = 5

    ctrl._bank = WordBank(tuple(_entry(i) for i in range(1, 13)))
    ctrl._rng = random.Random(0)
    ctrl._picker = WeightedWordPicker(ctrl._bank, ctrl._rng)

    ctrl._mastered = MasteredStore(tmp_path / "mastered.json")
    ctrl._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    ctrl._vocab = VocabStore(tmp_path / "vocab.json")
    ctrl._mastered.load()
    ctrl._daily_log.load()
    ctrl._vocab.load()

    ctrl._today_str = _DAY
    ctrl._last_bubble_ts = float("-inf")
    ctrl._wall_now = lambda: 1000.0
    ctrl._now_iso = lambda: _ISO
    ctrl._next_review_wall_ts = float("inf")
    return ctrl


def _seed_weak(ctrl: PetAppController, count: int = 2) -> None:
    """种入 ``count`` 个忘过 2 次的词（跨两天），并置脏标记待重算。"""

    for i in range(1, count + 1):
        for day in ("2024-12-31", _DAY):
            ctrl._daily_log.add_entry(day, _lapse_log_entry(i))
    ctrl._weak_dirty = True


# --------------------------------------------------------------------------- #
# 每日一次提醒（排期制）
# --------------------------------------------------------------------------- #
def test_reminder_waits_for_scheduled_time(ctrl: PetAppController) -> None:
    """未到随机延迟时刻：不提醒、不置标志。"""

    _seed_weak(ctrl)
    ctrl._next_weak_remind_ts = 500.0
    ctrl._maybe_remind_weak_words(100.0)
    assert ctrl._weak_reminded is False


def test_reminder_fires_once_per_day(ctrl: PetAppController) -> None:
    """到点后：置当日标志（随后不再触发）。"""

    _seed_weak(ctrl, count=2)
    ctrl._next_weak_remind_ts = 100.0
    ctrl._maybe_remind_weak_words(100.0)
    assert ctrl._weak_reminded is True
    # 已提醒：再调用直接返回
    ctrl._maybe_remind_weak_words(200.0)
    assert ctrl._weak_reminded is True


def test_reminder_requires_jp_enabled(ctrl: PetAppController) -> None:
    """日语学习关闭：不提醒。"""

    ctrl._cfg.jp_enabled = False
    _seed_weak(ctrl)
    ctrl._next_weak_remind_ts = 0.0
    ctrl._maybe_remind_weak_words(100.0)
    assert ctrl._weak_reminded is False


def test_reminder_requires_config_enabled(ctrl: PetAppController) -> None:
    """weak_review_enabled 关闭：不提醒（配置 round-trip 由 config 测试覆盖）。"""

    ctrl._cfg.weak_review_enabled = False
    _seed_weak(ctrl)
    ctrl._next_weak_remind_ts = 0.0
    ctrl._maybe_remind_weak_words(100.0)
    assert ctrl._weak_reminded is False


def test_reminder_without_weak_words_marks_day_done(ctrl: PetAppController) -> None:
    """无易错词：到点后当日标记已提醒，不再逐帧重试。"""

    ctrl._next_weak_remind_ts = 0.0
    ctrl._maybe_remind_weak_words(100.0)
    assert ctrl._weak_reminded is True
    assert ctrl._weak_words_top() == ()


# --------------------------------------------------------------------------- #
# 抽取加权接线
# --------------------------------------------------------------------------- #
def test_show_word_bubble_passes_boost_ids(ctrl: PetAppController) -> None:
    """_show_word_bubble 把易错词 TopN 作为 boost_ids 传给加权抽取器。"""

    _seed_weak(ctrl, count=2)
    captured: dict[str, set[str]] = {}

    original_pick = ctrl._picker.pick

    def _spy(level, excluded, vocab_ids, boost_ids=None):
        captured["boost"] = set(boost_ids or set())
        return original_pick(level, excluded, vocab_ids, boost_ids=boost_ids)

    ctrl._picker.pick = _spy  # type: ignore[method-assign]
    ctrl._show_word_bubble(0.0, bypass_gap=True)

    assert captured["boost"] >= {"n5-0001", "n5-0002"}


def test_lapse_marks_weak_cache_dirty(ctrl: PetAppController) -> None:
    """真实遗忘处置（_dispose_review 忘了分支）→ 脏标记置位，下次取用重算。"""

    entry = _entry(3)
    ctrl._mastered.add(entry, _ISO, stage=0, due_at="2020-01-01T00:00:00Z")
    item = ctrl._mastered.get(entry.id)
    assert item is not None
    ctrl._begin_review(item, 0.0)
    assert ctrl._reviewing is True

    ctrl._weak_dirty = False
    ctrl._dispose_review(False, 0.5)
    assert ctrl._weak_dirty is True
    # 重算后该词因本次遗忘落入易错集合之外（仅 1 次 < 阈值 2），缓存被清除脏标记
    assert ctrl._weak_words_top() == ()
    assert ctrl._weak_dirty is False


def test_two_lapses_produce_weak_word(ctrl: PetAppController) -> None:
    """端到端：同一词忘过 2 次（跨两天）→ _weak_words_top 派生出该词。"""

    for day in ("2024-12-31", _DAY):
        ctrl._daily_log.add_entry(day, _lapse_log_entry(3))
    ctrl._weak_dirty = True
    weak = ctrl._weak_words_top()
    assert [w.id for w in weak] == ["n5-0003"]
    assert weak[0].lapsed_count == 2
