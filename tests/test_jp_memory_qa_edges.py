"""QA（严过关）独立补充边界测试 —— 证明而非轻信工程师自测。

针对工程师测试可能漏掉/断言偏弱的边界，独立补写：
1. 超时与点击竞态的**反向顺序**（点击先 → 超时帧丢弃）与**真实帧循环超时路径**。
2. 情绪气泡在学习词展示期间被抑制（设计 §1.5 互斥守卫，原测试未覆盖）。
3. `_show_word_bubble` 在已有词展示时 no-op（不重复抽取）。
4. 每日上限 / all_mastered 到达后 `_show_word_bubble` 不再展示（而非仅测 `_jp_stop_for_today`）。
5. 跨日：注入两个 day 字符串，新 day 计数从 0 起，已掌握/生词本不重置。
6. 权重 3:1 大样本统计（更紧的置信区间）。

全部只读不改源码；新增文件，不修改工程师既有测试。
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


def _entry(i: int = 1, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}",
        kana="かな", translation="译", meaning="义",
    )


def _log_entry(i: int, status: str, day: str = "2025-01-01") -> DailyLogEntry:
    return DailyLogEntry.from_entry(_entry(i), f"{day}T00:00:0{i}Z", status)


@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path, monkeypatch) -> PetAppController:
    """构造最小 controller；store 指向 tmp_path；注入 3 词小词库并固定本地日期。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.jp_enabled = True
    ctrl._cfg.bubble_enabled = True
    ctrl._cfg.jp_level = "N5"
    ctrl._cfg.jp_daily_limit = 5
    ctrl._cfg.jp_bubble_duration_s = 30.0

    entries = tuple(_entry(i) for i in range(1, 4))
    ctrl._bank = WordBank(entries)
    ctrl._picker = WeightedWordPicker(ctrl._bank, random.Random(0))

    ctrl._mastered = MasteredStore(tmp_path / "mastered.json")
    ctrl._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    ctrl._vocab = VocabStore(tmp_path / "vocab.json")
    ctrl._mastered.load()
    ctrl._daily_log.load()
    ctrl._vocab.load()

    # 固定本地日期，隔离真实时钟（跨日检测依赖 _local_date_str）
    monkeypatch.setattr(ctrl, "_local_date_str", lambda: "2025-01-01")
    ctrl._today_str = "2025-01-01"
    ctrl._last_bubble_ts = float("-inf")
    return ctrl


# --------------------------------------------------------------------------- #
# 1. 竞态：反向顺序（点击先 → 超时帧被丢弃）
# --------------------------------------------------------------------------- #
def test_click_then_timeout_frame_is_discarded(controller: PetAppController) -> None:
    controller._show_word_bubble(0.0)
    assert controller._current_word is not None

    # 用户先点「记住了」
    controller._dispose_word(C.DAILY_LOG_STATUS_MASTERED, 1.0)
    assert controller._mastered.count() == 1
    assert controller._daily_log.count_for("2025-01-01") == 1

    # 随后帧循环到达 deadline（31 >= 0 + 30）：不应再落「未处理」
    controller._on_frame_tick(31.0)

    assert controller._daily_log.count_for("2025-01-01") == 1
    assert controller._daily_log.unprocessed_count_for("2025-01-01") == 0
    assert controller._daily_log.mastered_count_for("2025-01-01") == 1


# --------------------------------------------------------------------------- #
# 2. 真实帧循环超时路径（非直接调 _dispose_word）
# --------------------------------------------------------------------------- #
def test_frame_tick_timeout_records_unprocessed(controller: PetAppController) -> None:
    controller._show_word_bubble(0.0)  # deadline = 0 + 30 = 30.0
    controller._cfg.bubble_enabled = False  # 仅隔离情绪气泡，不影响超时判定

    controller._on_frame_tick(30.5)  # >= deadline

    assert controller._current_word is None
    assert controller._daily_log.unprocessed_count_for("2025-01-01") == 1
    assert controller._daily_log.count_for("2025-01-01") == 1
    assert controller._mastered.count() == 0
    assert controller._vocab.count() == 0


# --------------------------------------------------------------------------- #
# 3. 学习词展示期间抑制情绪气泡（设计 §1.5 互斥守卫）
# --------------------------------------------------------------------------- #
def test_emotion_bubble_suppressed_while_word_showing(controller: PetAppController) -> None:
    controller._show_word_bubble(0.0)
    assert controller._current_word is not None

    before = controller._bubble._text
    controller._show_bubble_for(C.Expression.HAPPY, 0.5)
    # 互斥守卫：情绪气泡不得覆盖学习词气泡
    assert controller._bubble._text == before


# --------------------------------------------------------------------------- #
# 4. 已有词展示时不再重复抽取
# --------------------------------------------------------------------------- #
def test_show_word_bubble_noop_when_current_word_exists(controller: PetAppController) -> None:
    controller._show_word_bubble(0.0)
    first = controller._current_word
    assert first is not None

    controller._show_word_bubble(1.0)  # 期间再次到点
    assert controller._current_word is first
    assert controller._daily_log.count_for("2025-01-01") == 0  # 未落任何记录


# --------------------------------------------------------------------------- #
# 5. 每日上限 / all_mastered 到达后不再展示
# --------------------------------------------------------------------------- #
def test_daily_limit_reached_no_show(controller: PetAppController) -> None:
    for i in range(1, 6):  # limit = 5
        controller._daily_log.add_entry(
            "2025-01-01", _log_entry(i, C.DAILY_LOG_STATUS_UNPROCESSED)
        )
    controller._show_word_bubble(0.0)
    assert controller._current_word is None


def test_all_mastered_early_stop_no_show(controller: PetAppController) -> None:
    # shown=2 > 0 且 mastered==2，未达上限 5，也应提前停
    controller._daily_log.add_entry("2025-01-01", _log_entry(1, C.DAILY_LOG_STATUS_MASTERED))
    controller._daily_log.add_entry("2025-01-01", _log_entry(2, C.DAILY_LOG_STATUS_MASTERED))
    assert controller._jp_stop_for_today() is True
    controller._show_word_bubble(0.0)
    assert controller._current_word is None


# --------------------------------------------------------------------------- #
# 6. 跨日重置（store 层：注入两个 day，新 day 计数从 0，掌握/生词不重置）
# --------------------------------------------------------------------------- #
def test_cross_day_store_bucketing_keeps_long_term(tmp_path: Path) -> None:
    mastered = MasteredStore(tmp_path / "mastered.json")
    vocab = VocabStore(tmp_path / "vocab.json")
    daily = DailyLogStore(tmp_path / "daily_log.json")

    mastered.add(_entry(1), "t")
    vocab.add(_entry(2), "t")

    daily.add_entry("2025-01-01", _log_entry(1, C.DAILY_LOG_STATUS_MASTERED))
    daily.add_entry("2025-01-01", _log_entry(2, C.DAILY_LOG_STATUS_VOCAB))
    daily.add_entry("2025-01-01", _log_entry(3, C.DAILY_LOG_STATUS_UNPROCESSED))

    # 新的一天：计数从 0 起
    assert daily.count_for("2025-01-02") == 0
    assert daily.shown_ids_for("2025-01-02") == set()
    assert daily.all_mastered("2025-01-02") is False

    # 长期数据不受日期影响
    assert mastered.count() == 1
    assert vocab.count() == 1
    assert mastered.ids() == {"n5-0001"}

    # 旧日记录仍可回查
    assert daily.count_for("2025-01-01") == 3


# --------------------------------------------------------------------------- #
# 7. 权重 3:1 大样本统计（更紧置信区间）
# --------------------------------------------------------------------------- #
def test_vocab_weight_three_to_one_statistical() -> None:
    """vocab=3.0 vs 普通=1.0：大样本下 vocab 命中率趋近 3/(3+4)=0.4286。"""

    bank = WordBank(tuple(_entry(i) for i in range(1, 6)))
    picker = WeightedWordPicker(bank, random.Random(20240606))
    vocab_ids = {"n5-0001"}
    n = 60_000
    hits = sum(
        1 for _ in range(n)
        if picker.pick("N5", set(), vocab_ids).id == "n5-0001"
    )
    ratio = hits / n
    # 理论 0.4286；1:1 时会是 0.2；留 3σ 余量（σ≈0.002）
    assert 0.41 <= ratio <= 0.45, f"权重未按 3:1 生效：ratio={ratio:.4f}"
