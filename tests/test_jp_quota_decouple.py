"""工程师自测：手动「立即显示」与每日配额解耦 + 自动间隔随机化（30s~10min）。

覆盖需求 R1 / R2 / R3 与产品决策 D1 / D2：
1. 常量：``JP_WORD_MIN_INTERVAL_S == 30.0`` / ``JP_WORD_MAX_INTERVAL_S == 600.0``，
   且 ``_schedule_next_word`` 采样间隔落在 ``[30, 600]``。
2. 连续手动点击：每日计数恒为 0（不计入配额）。
3. 配额已满时手动仍能展示，且计数不变、不置 ``_today_done_notified``。
4. 手动词点「记住了」→ 写 mastered（D1），但不写每日日志。
5. 手动词点「新单词」→ 写生词本（D1），但不写每日日志。
6. 手动词超时未处理 → 不写每日日志。
7. 手动词参与「当日不重复展示」去重（D2）；跨日清空。
8. 自动路径仍严格受每日配额约束。

全部为新增用例，不改动源码；遵循项目测试隔离约定（配置/数据落 tmp_path）。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker
from desktop_pet.core.word_detail_bank import WordDetailBank
from desktop_pet.core.word_details_cache_store import WordDetailsCacheStore

_DAY: str = "2025-01-01"
_LIMIT: int = 5


def _entry(i: int, level: str = "N5") -> VocabEntry:
    """构造第 ``i`` 个测试词条（id 形如 ``n5-0001``）。"""

    return VocabEntry(
        id=f"{level.lower()}-{i:04d}",
        level=level,
        word=f"語{i}",
        kana="かな",
        translation="译",
        meaning="义",
    )


def _log_entry(i: int, status: str, day: str = _DAY) -> DailyLogEntry:
    """构造一条每日日志记录。"""

    return DailyLogEntry.from_entry(_entry(i), f"{day}T00:00:0{i}Z", status)


@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """构造最小 controller：12 词小词库 + 每日上限 5，全部数据落 tmp_path。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.jp_enabled = True
    ctrl._cfg.bubble_enabled = True
    ctrl._cfg.jp_level = "N5"
    ctrl._cfg.jp_daily_limit = _LIMIT
    ctrl._cfg.jp_bubble_duration_s = 30

    ctrl._bank = WordBank(tuple(_entry(i) for i in range(1, 13)))
    ctrl._rng = random.Random(0)
    ctrl._picker = WeightedWordPicker(ctrl._bank, ctrl._rng)

    ctrl._mastered = MasteredStore(tmp_path / "mastered.json")
    ctrl._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    ctrl._vocab = VocabStore(tmp_path / "vocab.json")
    ctrl._mastered.load()
    ctrl._daily_log.load()
    ctrl._vocab.load()

    ctrl._detail_cache = WordDetailsCacheStore(tmp_path / "word_details_cache.json")
    ctrl._detail_cache.load()
    ctrl._detail_bank = WordDetailBank.empty()

    ctrl._today_str = _DAY
    ctrl._last_bubble_ts = float("-inf")
    ctrl._today_done_notified = False
    return ctrl


def _fill_quota(ctrl: PetAppController, count: int = _LIMIT) -> None:
    """向当日日志塞入 ``count`` 条「未处理」记录，用于模拟配额已满。"""

    for i in range(1, count + 1):
        ctrl._daily_log.add_entry(_DAY, _log_entry(i, C.DAILY_LOG_STATUS_UNPROCESSED))


# --------------------------------------------------------------------------- #
# 1. 常量与自动间隔随机化（R3）
# --------------------------------------------------------------------------- #
def test_interval_constants_are_30s_to_600s() -> None:
    """自动展示间隔常量应为 30s ~ 600s（30 秒 ~ 10 分钟）。"""

    assert C.JP_WORD_MIN_INTERVAL_S == 30.0
    assert C.JP_WORD_MAX_INTERVAL_S == 600.0
    assert C.JP_WORD_MIN_INTERVAL_S < C.JP_WORD_MAX_INTERVAL_S


def test_scheduled_interval_samples_within_bounds(controller: PetAppController) -> None:
    """``_schedule_next_word`` 采样间隔必须全部落在 [30, 600]，且确实拓宽到旧范围之外。"""

    deltas: list[float] = []
    for _ in range(300):
        controller._schedule_next_word(1000.0)
        # 关闭学习时置 inf；此处 jp_enabled=True 且词库非空 → 必然为有限值
        assert controller._next_word_ts != float("inf")
        deltas.append(controller._next_word_ts - 1000.0)

    assert all(30.0 <= d <= 600.0 for d in deltas), f"越界采样：{min(deltas)}~{max(deltas)}"
    # 旧范围为 25~50s；300 次采样中最大值应显著超过 50，证明确实拓宽
    assert max(deltas) > 50.0
    # 覆盖到新上界附近（uniform → 300 次采样几乎必然接近 600）
    assert max(deltas) > 500.0


# --------------------------------------------------------------------------- #
# 2. 连续手动点击：每日计数恒为 0（R1）
# --------------------------------------------------------------------------- #
def test_consecutive_manual_clicks_keep_count_zero(controller: PetAppController) -> None:
    """连续 5 次「立即显示」：每日计数恒为 0，且手动词互不重复（当日去重 D2）。"""

    shown_ids: list[str] = []
    for _ in range(5):
        controller._on_jp_show_now()
        assert controller._current_word is not None
        shown_ids.append(controller._current_word.id)
        assert controller._daily_log.count_for(_DAY) == 0

    # 前 4 次点击各处置掉一个手动词 → 去重集合 4 个；第 5 个仍在展示中
    assert len(shown_ids) == len(set(shown_ids)) == 5
    assert len(controller._manual_shown_ids_today) == 4
    assert controller._daily_log.count_for(_DAY) == 0


# --------------------------------------------------------------------------- #
# 3. 配额已满：手动仍可展示、计数不变、不置一次性标志位（R1/R2）
# --------------------------------------------------------------------------- #
def test_manual_allowed_when_quota_full_count_unchanged(controller: PetAppController) -> None:
    """配额已满时手动仍能展示；count 不变；不置 ``_today_done_notified``。"""

    _fill_quota(controller)
    assert controller._jp_stop_for_today() is True
    controller._today_done_notified = False

    controller._on_jp_show_now()

    assert controller._current_word is not None
    assert controller._daily_log.count_for(_DAY) == _LIMIT
    assert controller._today_done_notified is False


def test_manual_full_quota_uses_over_limit_feedback(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配额已满的手动展示反馈应为「不计入每日数量」专用文案，而非普通文案。"""

    _fill_quota(controller)
    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_jp_show_now()

    word = controller._current_word
    assert word is not None
    expected = C.JP_NOTIFY_SHOW_NOW_OVER_LIMIT.format(
        word=word.word, kana=word.kana, count=_LIMIT, limit=_LIMIT
    )
    assert expected in captured
    assert C.JP_NOTIFY_SHOW_NOW.format(word=word.word, kana=word.kana) not in captured


def test_manual_below_quota_uses_plain_feedback(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """配额未满的手动展示反馈应为普通「已立即显示」文案。"""

    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_jp_show_now()

    word = controller._current_word
    assert word is not None
    assert C.JP_NOTIFY_SHOW_NOW.format(word=word.word, kana=word.kana) in captured
    assert C.JP_NOTIFY_SHOW_NOW_OVER_LIMIT.format(
        word=word.word, kana=word.kana, count=0, limit=_LIMIT
    ) not in captured


# --------------------------------------------------------------------------- #
# 4/5/6. 手动词处置：写长期数据但不写每日日志（D1）
# --------------------------------------------------------------------------- #
def test_manual_mastered_writes_mastered_not_daily(controller: PetAppController) -> None:
    """手动词点「记住了」：mastered +1，但每日日志为 0。"""

    controller._on_jp_show_now()
    word = controller._current_word
    assert word is not None

    controller._on_word_mastered()

    assert controller._mastered.count() == 1
    assert word.id in controller._mastered.ids()
    assert controller._daily_log.count_for(_DAY) == 0
    assert word.id not in controller._daily_log.shown_ids_for(_DAY)
    # 手动词计入当日去重集合
    assert word.id in controller._manual_shown_ids_today


def test_manual_vocab_writes_vocab_not_daily(controller: PetAppController) -> None:
    """手动词点「新单词」：生词本 +1，但每日日志为 0。"""

    controller._on_jp_show_now()
    word = controller._current_word
    assert word is not None

    controller._on_word_vocab()

    assert len(controller._vocab.items()) == 1
    assert {item.id for item in controller._vocab.items()} == {word.id}
    assert controller._daily_log.count_for(_DAY) == 0
    assert word.id in controller._manual_shown_ids_today


def test_manual_timeout_writes_no_daily(controller: PetAppController) -> None:
    """手动词超时未处理：不写每日日志（每日配额不被手动操作影响）。"""

    controller._on_jp_show_now()
    word = controller._current_word
    assert word is not None

    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 999.0)

    assert controller._daily_log.count_for(_DAY) == 0
    assert controller._daily_log.unprocessed_count_for(_DAY) == 0
    assert word.id in controller._manual_shown_ids_today


# --------------------------------------------------------------------------- #
# 7. 手动词参与当日去重（D2）与跨日清空
# --------------------------------------------------------------------------- #
def test_manual_word_excluded_from_reselection_same_day(controller: PetAppController) -> None:
    """手动词处置后（未落每日日志）仍被当日排除，不会立刻重复展示同一个词。"""

    controller._on_jp_show_now()
    first = controller._current_word
    assert first is not None

    # 处置为「未处理」：不进 mastered、不进每日日志，仅在内存级手动去重集合中
    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 1.0)
    assert controller._daily_log.count_for(_DAY) == 0
    assert first.id in controller._manual_shown_ids_today

    controller._on_jp_show_now()
    second = controller._current_word
    assert second is not None
    assert second.id != first.id


def test_manual_ids_cleared_on_cross_day(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跨日：内存级当日手动去重集合被清空，日期推进。"""

    controller._manual_shown_ids_today.add("n5-0001")
    controller._manual_shown_ids_today.add("n5-0002")
    controller._cfg.jp_enabled = False  # 隔离跨日分支，避免到点展示干扰
    controller._today_str = _DAY
    monkeypatch.setattr(controller, "_local_date_str", lambda: "2025-01-02")

    controller._on_frame_tick(100.0)

    assert controller._today_str == "2025-01-02"
    assert controller._manual_shown_ids_today == set()


# --------------------------------------------------------------------------- #
# 8. 自动路径仍严格受每日配额约束（R2）
# --------------------------------------------------------------------------- #
def test_auto_path_still_bound_by_daily_quota(controller: PetAppController) -> None:
    """配额已满时自动路径（manual=False）被拦截，不展示新词。"""

    _fill_quota(controller)
    assert controller._jp_stop_for_today() is True

    controller._show_word_bubble(0.0)  # 自动路径

    assert controller._current_word is None
    assert controller._daily_log.count_for(_DAY) == _LIMIT


def test_auto_path_counts_normally_below_quota(controller: PetAppController) -> None:
    """配额未满时自动路径正常展示；处置后每日计数 +1。"""

    controller._show_word_bubble(0.0)
    word = controller._current_word
    assert word is not None
    assert controller._word_manual is False

    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 1.0)

    assert controller._daily_log.count_for(_DAY) == 1
    assert word.id in controller._daily_log.shown_ids_for(_DAY)
    # 自动词不进手动去重集合
    assert word.id not in controller._manual_shown_ids_today


# --------------------------------------------------------------------------- #
# 附加：守卫反馈（严禁静默返回）
# --------------------------------------------------------------------------- #
def test_show_now_when_jp_disabled_notifies(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """学习开关关闭时点击「立即显示」：给出可见反馈，不展示词。"""

    controller._cfg.jp_enabled = False
    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_jp_show_now()

    assert controller._current_word is None
    assert C.JP_NOTIFY_JP_OFF in captured


def test_show_now_pool_exhausted_notifies(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """该等级词全部排除（池耗尽）时，手动展示给专用「学完」反馈，不展示词。"""

    # 把 12 个词全部加入当日日志排除集合
    for i in range(1, 13):
        controller._daily_log.add_entry(_DAY, _log_entry(i, C.DAILY_LOG_STATUS_UNPROCESSED))
    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_jp_show_now()

    assert controller._current_word is None
    assert C.JP_NOTIFY_POOL_EXHAUSTED.format(level=controller._cfg.jp_level) in captured
