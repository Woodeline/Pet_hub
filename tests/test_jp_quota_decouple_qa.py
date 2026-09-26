"""QA（严过关）独立验证：手动「立即显示」与每日配额解耦 + 自动间隔随机化。

与工程师自测（``tests/test_jp_quota_decouple.py``）**相互独立**：本文件不复用其夹具/
辅助函数，按验收基线 R1 / R2 / R3 与产品决策 D1 / D2 独立构造最小 controller，并额外
补齐工程师自测薄弱 / 未覆盖的路径：

- 真实**帧循环超时**（``_on_frame_tick``）对手动词的处置，而非只调 ``_dispose_word``；
- 手动词处置后**落盘隔离**（读 ``daily_log.json`` 实证，而非仅内存不计数）；
- ``_word_manual`` 在**守卫提前 return** 时不被污染（最关键隐性风险：污染会让下一个
  自动词被误判为手动，从而泄漏每日配额）；
- 交错序列的**精确计数**（证明「只受自动流程影响」而非「完全不计」）；
- 自动间隔**采样上界**确实拓宽到 600s（500 次采样的 max > 500 且 min < 60）；
- ``ignore_daily_limit`` 标识符静态消失检查。

全部为新增用例，**不改动任何源码**；遵循项目测试隔离约定（所有 store 落 ``tmp_path``）。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app import controller as controller_module
from desktop_pet.app.controller import PetAppController
from desktop_pet.ui import tray as tray_module
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.constants import Mood
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker
from desktop_pet.core.word_detail_bank import WordDetailBank
from desktop_pet.core.word_details_cache_store import WordDetailsCacheStore

_DAY: str = "2025-01-01"
_LIMIT: int = 5
_BANK_SIZE: int = 12


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
    """最小 controller：12 词小词库 + 每日上限 5，全部数据落 tmp_path。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.jp_enabled = True
    ctrl._cfg.bubble_enabled = True
    ctrl._cfg.jp_level = "N5"
    ctrl._cfg.jp_daily_limit = _LIMIT
    ctrl._cfg.jp_bubble_duration_s = 30

    ctrl._bank = WordBank(tuple(_entry(i) for i in range(1, _BANK_SIZE + 1)))
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
    ctrl._manual_shown_ids_today.clear()
    ctrl._word_manual = False
    return ctrl


def _fill_quota(ctrl: PetAppController, count: int = _LIMIT) -> None:
    """向当日日志塞入 ``count`` 条「未处理」记录，模拟配额已满。"""

    for i in range(1, count + 1):
        ctrl._daily_log.add_entry(_DAY, _log_entry(i, C.DAILY_LOG_STATUS_UNPROCESSED))


# =========================================================================== #
# 场景 1：连续手动点击 —— 配额恒为 0，且手动词当日互不重复（R1 / D2）
# =========================================================================== #
def test_consecutive_manual_clicks_count_zero_and_ids_unique(
    controller: PetAppController,
) -> None:
    """连续手动点击 12 次（每次落「未处理」，仅进内存去重集合）：count 恒 0，12 词 id 互不重复。

    刻意处置为「未处理」：手动词既不进 ``mastered`` 也不进 ``daily_log``，因此「当日不重复」
    只能由内存级 ``_manual_shown_ids_today`` 保证（若该集合不参与排除，去重即失效）。
    """

    shown_ids: list[str] = []
    for step in range(_BANK_SIZE):
        controller._on_jp_show_now()
        assert controller._current_word is not None, f"第 {step + 1} 次手动点击未弹出"
        shown_ids.append(controller._current_word.id)
        # 全程 count 不得增长
        assert controller._daily_log.count_for(_DAY) == 0, f"第 {step + 1} 次后 count 非 0"
        # 处置当前词为「未处理」：既不写长期数据，也不写每日日志
        controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, float(step))

    assert len(shown_ids) == _BANK_SIZE
    assert len(set(shown_ids)) == _BANK_SIZE, "手动词当日出现重复（D2 去重失效）"
    assert controller._daily_log.count_for(_DAY) == 0
    assert controller._mastered.count() == 0
    assert len(controller._manual_shown_ids_today) == _BANK_SIZE


# =========================================================================== #
# 场景 2：配额已满时手动仍成功（R1 / R2）
# =========================================================================== #
def test_manual_allowed_when_quota_full_count_unchanged_and_no_today_notify(
    controller: PetAppController,
) -> None:
    """配额已满时手动仍能弹出新词，count 不变，``_today_done_notified`` 保持 False。"""

    _fill_quota(controller)
    assert controller._jp_stop_for_today() is True
    controller._today_done_notified = False

    controller._on_jp_show_now()

    assert controller._current_word is not None
    assert controller._daily_log.count_for(_DAY) == _LIMIT
    assert controller._today_done_notified is False


# =========================================================================== #
# 场景 3：手动词保留长期数据、配额隔离（D1）
# =========================================================================== #
def test_manual_mastered_keeps_long_term_drops_quota(controller: PetAppController) -> None:
    """手动展示 → 「记住了」：mastered +1，daily_log 恒 0。"""

    controller._on_jp_show_now()
    word = controller._current_word
    assert word is not None

    controller._on_word_mastered()

    assert controller._mastered.count() == 1
    assert word.id in controller._mastered.ids()
    assert controller._daily_log.count_for(_DAY) == 0
    assert word.id not in controller._daily_log.shown_ids_for(_DAY)


def test_manual_vocab_keeps_long_term_drops_quota(controller: PetAppController) -> None:
    """手动展示 → 「新单词」：生词本 +1，daily_log 恒 0。"""

    controller._on_jp_show_now()
    word = controller._current_word
    assert word is not None

    controller._on_word_vocab()

    assert controller._vocab.count() == 1
    assert {item.id for item in controller._vocab.items()} == {word.id}
    assert controller._daily_log.count_for(_DAY) == 0
    assert word.id not in controller._daily_log.shown_ids_for(_DAY)


# =========================================================================== #
# 场景 4：手动词超时不写日志 —— 真实帧循环超时 + 直接处置双路径
# =========================================================================== #
def test_manual_timeout_via_frame_loop_writes_no_daily(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """手动词经**真实帧循环超时**（``_on_frame_tick``）处置：不写每日日志。"""

    # 固定日期，避免跨日分支清空/改写状态
    monkeypatch.setattr(controller, "_local_date_str", lambda: _DAY)

    controller._show_word_bubble(100.0, bypass_gap=True, manual=True)
    word = controller._current_word
    assert word is not None
    assert controller._word_manual is True
    deadline = controller._word_deadline

    # 帧循环到点：now >= deadline → 记「未处理」
    controller._on_frame_tick(deadline + 0.5)

    assert controller._current_word is None
    assert controller._daily_log.count_for(_DAY) == 0
    assert controller._daily_log.unprocessed_count_for(_DAY) == 0
    assert word.id in controller._manual_shown_ids_today


def test_manual_unprocessed_dispose_writes_no_daily(controller: PetAppController) -> None:
    """手动词直接处置为「未处理」：每日日志与「未处理」计数均为 0。"""

    controller._on_jp_show_now()
    word = controller._current_word
    assert word is not None

    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 999.0)

    assert controller._daily_log.count_for(_DAY) == 0
    assert controller._daily_log.unprocessed_count_for(_DAY) == 0
    assert word.id in controller._manual_shown_ids_today


# =========================================================================== #
# 场景 5：落盘隔离 —— 读 daily_log.json 实证「不落盘」
# =========================================================================== #
def test_manual_dispose_not_persisted_to_disk(
    controller: PetAppController, tmp_path: Path
) -> None:
    """手动词处置后：磁盘当日桶不存在/为空；对照组（自动路径）则确实落盘。"""

    log_path = tmp_path / "daily_log.json"

    controller._on_jp_show_now()
    assert controller._current_word is not None
    controller._on_word_mastered()

    # ① 直接读磁盘：当日桶必须不存在或为空
    if log_path.exists():
        data = json.loads(log_path.read_text(encoding="utf-8"))
        days = data.get("days", {}) if isinstance(data, dict) else {}
        assert not days.get(_DAY), "手动词竟落盘了当日记录"
    # ② 全新 store 重新加载：count 必须为 0（不依赖内存态）
    fresh = DailyLogStore(log_path)
    fresh.load()
    assert fresh.count_for(_DAY) == 0

    # ③ 对照组：自动路径确实会落盘 +1（证明本断言确有区分力，非恒真）
    controller._show_word_bubble(200.0, bypass_gap=True)  # 自动路径
    auto_word = controller._current_word
    assert auto_word is not None
    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 201.0)

    assert log_path.exists(), "自动路径处置后应已落盘"
    data = json.loads(log_path.read_text(encoding="utf-8"))
    assert len(data["days"][_DAY]) == 1
    fresh2 = DailyLogStore(log_path)
    fresh2.load()
    assert fresh2.count_for(_DAY) == 1


# =========================================================================== #
# 场景 6：``_word_manual`` 不被守卫 return 污染（最关键隐性风险）
# =========================================================================== #
def test_show_word_bubble_guard_hits_do_not_pollute_word_manual(
    controller: PetAppController,
) -> None:
    """气泡关 / 已有词在展示 / 睡觉 三种守卫命中：提前 return 且 ``_word_manual`` 不被置 True。"""

    # (a) 气泡关闭
    controller._cfg.bubble_enabled = False
    controller._show_word_bubble(0.0, manual=True)
    assert controller._current_word is None
    assert controller._word_manual is False

    # 复位后 (b) 已有词在展示（自动词）
    controller._cfg.bubble_enabled = True
    controller._show_word_bubble(0.0)  # 自动词
    auto_word = controller._current_word
    assert auto_word is not None
    assert controller._word_manual is False

    controller._show_word_bubble(1.0, manual=True)  # 命中「已有词」守卫
    assert controller._current_word is auto_word  # 未被替换
    assert controller._word_manual is False  # 未被污染

    # (c) 睡觉态
    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 2.0)
    controller._sm._state = Mood.SLEEP
    controller._show_word_bubble(3.0, manual=True)
    assert controller._current_word is None
    assert controller._word_manual is False


def test_guard_hit_manual_call_does_not_leak_quota_on_auto_dispose(
    controller: PetAppController,
) -> None:
    """守卫命中后紧接着处置自动词：仍应正常 +1（若 ``_word_manual`` 被误置 True 则泄漏）。"""

    controller._show_word_bubble(0.0)  # 自动词 A
    word = controller._current_word
    assert word is not None

    controller._show_word_bubble(1.0, manual=True)  # 守卫命中，不应污染 _word_manual
    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 2.0)  # 处置真正的自动词

    assert controller._daily_log.count_for(_DAY) == 1, "自动词被误判为手动，配额泄漏"
    assert word.id in controller._daily_log.shown_ids_for(_DAY)
    assert word.id not in controller._manual_shown_ids_today


# =========================================================================== #
# 场景 7：交错序列精确计数 —— 只受自动流程影响（R2）
# =========================================================================== #
def test_interleaved_sequence_exact_count(controller: PetAppController) -> None:
    """自动 → 手动 → 自动 交错：count 只被自动流程推进（0→1→1→1→2）。"""

    # 1) 自动弹词 A
    controller._show_word_bubble(0.0)
    word_a = controller._current_word
    assert word_a is not None
    assert controller._daily_log.count_for(_DAY) == 0

    # 2) 手动弹词：先等价超时处置旧自动词 A（+1），再弹手动词 B
    controller._on_jp_show_now()
    word_b = controller._current_word
    assert word_b is not None
    assert word_b.id != word_a.id
    assert controller._daily_log.count_for(_DAY) == 1  # A 计入
    assert word_a.id in controller._daily_log.shown_ids_for(_DAY)

    # 3) 处置手动词 B：不计入
    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, controller._last_bubble_ts + 1.0)
    assert controller._daily_log.count_for(_DAY) == 1  # 仍为 1

    # 4) 自动弹词 C
    t = controller._last_bubble_ts + C.BUBBLE_MIN_GAP_S + 1.0
    controller._show_word_bubble(t)
    word_c = controller._current_word
    assert word_c is not None
    assert word_c.id not in {word_a.id, word_b.id}
    assert controller._daily_log.count_for(_DAY) == 1

    # 5) 处置自动词 C：+1
    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, t + 1.0)
    assert controller._daily_log.count_for(_DAY) == 2

    # 手动词 B 仅在内存去重集合，不在每日日志
    assert word_b.id in controller._manual_shown_ids_today
    assert word_b.id not in controller._daily_log.shown_ids_for(_DAY)


# =========================================================================== #
# 场景 8：跨日清空内存级手动去重集合（D2）
# =========================================================================== #
def test_manual_ids_cleared_cross_day(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """跨日：``_manual_shown_ids_today`` 被 clear()，日期推进。"""

    controller._manual_shown_ids_today.add("n5-0001")
    controller._manual_shown_ids_today.add("n5-0002")
    controller._cfg.jp_enabled = False  # 隔离自动展示分支
    monkeypatch.setattr(controller, "_local_date_str", lambda: "2025-01-02")

    controller._on_frame_tick(100.0)

    assert controller._today_str == "2025-01-02"
    assert controller._manual_shown_ids_today == set()


# =========================================================================== #
# 场景 9：自动路径回归（R2）
# =========================================================================== #
def test_auto_path_blocked_when_quota_full(controller: PetAppController) -> None:
    """配额已满时自动路径（manual 默认 False）仍被拦截。"""

    _fill_quota(controller)
    assert controller._jp_stop_for_today() is True

    controller._show_word_bubble(0.0)

    assert controller._current_word is None
    assert controller._daily_log.count_for(_DAY) == _LIMIT


def test_auto_path_counts_normally_below_quota(controller: PetAppController) -> None:
    """配额未满时自动路径正常展示，处置后 count +1，且不进手动去重集合。"""

    controller._show_word_bubble(0.0)
    word = controller._current_word
    assert word is not None
    assert controller._word_manual is False

    controller._dispose_word(C.DAILY_LOG_STATUS_UNPROCESSED, 1.0)

    assert controller._daily_log.count_for(_DAY) == 1
    assert word.id in controller._daily_log.shown_ids_for(_DAY)
    assert word.id not in controller._manual_shown_ids_today


# =========================================================================== #
# 场景 10：R3 常量与采样（30s ~ 600s）
# =========================================================================== #
def test_interval_constants_literal() -> None:
    """常量必须恰为字面量 30.0 / 600.0。"""

    assert C.JP_WORD_MIN_INTERVAL_S == 30.0
    assert C.JP_WORD_MAX_INTERVAL_S == 600.0


def test_schedule_next_word_sampling_bounds(controller: PetAppController) -> None:
    """采样 500 次：全部落在 [30, 600]；max > 500（拓宽到 10min）；min < 60（仍会快速出现）。"""

    deltas: list[float] = []
    for _ in range(500):
        controller._schedule_next_word(1000.0)
        assert controller._next_word_ts != float("inf")
        deltas.append(controller._next_word_ts - 1000.0)

    assert all(30.0 <= d <= 600.0 for d in deltas), f"越界采样：{min(deltas)}~{max(deltas)}"
    assert max(deltas) > 500.0, f"上界未拓宽（max={max(deltas)}）"
    assert min(deltas) < 60.0, f"仍应快速出现（min={min(deltas)}）"


# =========================================================================== #
# 场景 11：池耗尽反馈（手动路径每次点击都必须有可见反馈）
# =========================================================================== #
def test_pool_exhausted_feedback_on_second_manual_click(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """词库仅 1 词：手动展示并处置后再点击 → 发出 ``JP_NOTIFY_POOL_EXHAUSTED``。"""

    controller._bank = WordBank((_entry(1),))
    controller._picker = WeightedWordPicker(controller._bank, controller._rng)

    captured: list[tuple[str, str]] = []
    monkeypatch.setattr(
        controller._tray, "notify", lambda title, msg: captured.append((title, msg))
    )

    controller._on_jp_show_now()
    assert controller._current_word is not None
    controller._dispose_word(C.DAILY_LOG_STATUS_MASTERED, 1.0)

    captured.clear()
    controller._on_jp_show_now()

    assert controller._current_word is None
    expected = C.JP_NOTIFY_POOL_EXHAUSTED.format(level=controller._cfg.jp_level)
    assert expected in [msg for _title, msg in captured], f"未收到池耗尽反馈：{captured}"


# =========================================================================== #
# 场景 12：静态检查
# =========================================================================== #
def test_no_ignore_daily_limit_identifier_static() -> None:
    """源码中不得残留 ``ignore_daily_limit`` 标识符（旧方案已彻底移除）。"""

    ctrl_src = Path(controller_module.__file__).read_text(encoding="utf-8")
    assert "ignore_daily_limit" not in ctrl_src

    tray_src = Path(tray_module.__file__).read_text(encoding="utf-8")
    assert "ignore_daily_limit" not in tray_src


def test_tray_show_now_wiring_intact() -> None:
    """``ui/tray.py`` 未受影响：立即显示信号与菜单项仍在。"""

    tray_src = Path(tray_module.__file__).read_text(encoding="utf-8")
    assert "jp_show_now_requested" in tray_src
    assert "JP_MENU_SHOW_NOW" in tray_src
