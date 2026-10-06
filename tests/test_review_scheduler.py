"""工程师自测：记忆曲线复习调度 —— controller 侧的排期 / 复习优先 / 两态处置 / 顺延。

覆盖：
1. 掌握即入 SRS：气泡 / 详情「记住了」→ stage=0、首轮 due = 掌握时间 + 1 天，
   复习排期（``_next_review_wall_ts``）即时重估。
2. 复习优先：有到期复习时 ``_show_word_bubble`` 先弹复习卡片（隐藏翻译、
   按钮条切复习模式），且**不受每日配额约束**；手动「立即显示」不被复习抢位。
3. 到期唤醒：``_maybe_wake_for_review`` 在墙钟越过最早 due 时把单词排期提前；
   学习关闭 / 正在展示 / 未到期时不动作。
4. 两态处置：还记得 → 阶段 +1（隔 3 天再考）+ 写 ``review_ok`` 日志；最后一轮
   通过 → 毕业（due_at=""、不再排期）；忘了 → 移出掌握集合 + 退回生词本 +
   写 ``review_lapsed`` 日志。
5. 超时顺延：两按钮都没点 → 不算遗忘、不推进阶段、不写日志，due 顺延 1 小时。
6. 复习态双击 = 偷看答案：打开详情但**不打断**复习（当前词保持、不落日志）。
7. v1 → v2 迁移：旧记录（due_at 空）经 ``_migrate_mastered_review`` 补首轮排期。

遵循项目测试隔离约定（配置 / 数据落 tmp_path，offscreen 渲染，墙钟注入替身）。
"""

from __future__ import annotations

import json
import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController, _iso_shift, _iso_to_wall
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker
from desktop_pet.core.word_detail_bank import WordDetailBank
from desktop_pet.core.word_details_cache_store import WordDetailsCacheStore

_DAY: str = "2025-01-01"
_ISO: str = "2025-01-01T00:00:00Z"
#: 过期 due（恒早于测试运行的真实墙钟 → 恒「已到期」，测试确定性强）
_ISO_PAST_DUE: str = "2020-01-01T00:00:00Z"
_WALL: float = 1000.0


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


@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """构造最小 controller（同 test_jp_detail_mastered 范式）+ 墙钟/ISO 替身。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.jp_enabled = True
    ctrl._cfg.bubble_enabled = True
    ctrl._cfg.jp_level = "N5"
    ctrl._cfg.jp_daily_limit = 5
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
    # 墙钟替身 + ISO 钉死：测试内完全确定，规避真实时钟跨秒不可复现
    ctrl._wall_now = lambda: _WALL
    ctrl._now_iso = lambda: _ISO
    ctrl._next_review_wall_ts = float("inf")
    return ctrl


def _seed_mastered(ctrl: PetAppController, entry: VocabEntry, stage: int = 0) -> None:
    """把词条以指定阶段种入已掌握集合，due 置为恒已过期的确定时刻。"""

    ctrl._mastered.add(entry, _ISO, stage=stage, due_at=_ISO_PAST_DUE)
    ctrl._refresh_review_schedule()


# --------------------------------------------------------------------------- #
# 1. 掌握即入 SRS
# --------------------------------------------------------------------------- #
def test_mastery_enters_srs_with_first_interval(controller: PetAppController) -> None:
    """「记住了」→ stage=0、due = 掌握时间 + 首轮间隔（1 天），排期即时重估。"""

    controller._show_word_bubble(0.0)
    word = controller._current_word
    assert word is not None
    controller._on_word_mastered()

    item = controller._mastered.get(word.id)
    assert item is not None
    assert item.stage == 0
    assert item.due_at == _iso_shift(_ISO, days=C.REVIEW_INTERVALS_DAYS[0])
    # 最早排期已被重估为该 due 的墙钟时刻（而非 inf）
    assert controller._next_review_wall_ts == _iso_to_wall(item.due_at)


# --------------------------------------------------------------------------- #
# 2. 复习优先 + 配额豁免
# --------------------------------------------------------------------------- #
def test_due_review_shown_before_new_word(controller: PetAppController) -> None:
    """有到期复习时，单词槽先弹复习卡片：隐藏翻译、按钮条切复习模式。"""

    entry = _entry(7)
    _seed_mastered(controller, entry, stage=0)

    assert controller._show_word_bubble(0.0) is None
    assert controller._current_word is not None
    assert controller._current_word.id == entry.id
    assert controller._reviewing is True
    assert controller._word_manual is False
    # 主动回忆形态：翻译行隐藏、提示语替代释义行
    assert controller._bubble._line_translation == ""
    assert controller._bubble._line_meaning == C.JP_BUBBLE_REVIEW_HINT
    # 按钮条切复习模式
    assert controller._button_bar._review_mode is True
    assert controller._button_bar._btn_mastered.text() == C.JP_BUTTON_REVIEW_OK
    assert controller._button_bar._btn_vocab.text() == C.JP_BUTTON_REVIEW_LAPSED


def test_review_not_blocked_by_daily_limit(controller: PetAppController) -> None:
    """复习不受每日配额约束：当日已达上限仍照常弹复习（新词才停）。"""

    entry = _entry(8)
    _seed_mastered(controller, entry, stage=0)
    # 灌满当日配额
    for i in range(controller._cfg.jp_daily_limit):
        controller._daily_log.add_entry(_DAY, _fake_log_entry(i))

    controller._show_word_bubble(0.0)
    assert controller._current_word is not None
    assert controller._current_word.id == entry.id
    assert controller._reviewing is True


def test_manual_show_now_not_hijacked_by_review(controller: PetAppController) -> None:
    """手动「立即显示一个新单词」明确要新词：到期复习不抢位。"""

    entry = _entry(9)
    _seed_mastered(controller, entry, stage=0)

    controller._show_word_bubble(0.0, bypass_gap=True, manual=True)
    assert controller._current_word is not None
    assert controller._current_word.id != entry.id
    assert controller._reviewing is False


def _fake_log_entry(i: int):
    from desktop_pet.core.daily_log_store import DailyLogEntry

    return DailyLogEntry.from_entry(_entry(20 + i), _ISO, C.DAILY_LOG_STATUS_VOCAB)


# --------------------------------------------------------------------------- #
# 3. 到期唤醒
# --------------------------------------------------------------------------- #
def test_wake_pulls_word_schedule_when_review_due(controller: PetAppController) -> None:
    """墙钟越过最早 due → 单词排期提前到当前帧。"""

    controller._next_word_ts = 5000.0
    controller._next_review_wall_ts = 100.0
    assert controller._wall_now() == _WALL

    controller._maybe_wake_for_review(now=42.0)
    assert controller._next_word_ts == 42.0


def test_wake_noop_when_not_due_or_busy(controller: PetAppController) -> None:
    """未到期 / 学习关闭 / 正在展示 → 不唤醒。"""

    controller._next_word_ts = 5000.0
    controller._next_review_wall_ts = 2000.0  # 未到期
    controller._maybe_wake_for_review(now=42.0)
    assert controller._next_word_ts == 5000.0

    controller._next_review_wall_ts = 100.0
    controller._cfg.jp_enabled = False
    controller._maybe_wake_for_review(now=42.0)
    assert controller._next_word_ts == 5000.0

    controller._cfg.jp_enabled = True
    controller._current_word = _entry(1)  # 正在展示（守卫交由 show_word_bubble）
    controller._maybe_wake_for_review(now=42.0)
    assert controller._next_word_ts == 5000.0


# --------------------------------------------------------------------------- #
# 4. 两态处置
# --------------------------------------------------------------------------- #
def test_review_ok_advances_stage_and_logs(controller: PetAppController) -> None:
    """「还记得」→ 阶段 +1、下轮 +3 天、写 review_ok 日志、仍在掌握集合。"""

    entry = _entry(5)
    _seed_mastered(controller, entry, stage=0)
    controller._show_word_bubble(0.0)
    assert controller._reviewing is True

    controller._on_review_ok()

    item = controller._mastered.get(entry.id)
    assert item is not None
    assert item.stage == 1
    assert item.due_at == _iso_shift(_ISO, days=C.REVIEW_INTERVALS_DAYS[1])
    assert item.review_count == 1
    assert entry.id in controller._mastered.ids()
    assert controller._current_word is None
    assert controller._reviewing is False
    entries = controller._daily_log.entries_for(_DAY)
    assert [e.status for e in entries] == [C.DAILY_LOG_STATUS_REVIEW_OK]


def test_review_ok_graduates_after_last_interval(controller: PetAppController) -> None:
    """最后一轮通过 → 毕业：stage 走完阶梯、due_at 清空、排期归 inf。"""

    last = len(C.REVIEW_INTERVALS_DAYS)
    entry = _entry(6)
    _seed_mastered(controller, entry, stage=last - 1)
    controller._show_word_bubble(0.0)

    controller._on_review_ok()

    item = controller._mastered.get(entry.id)
    assert item is not None
    assert item.stage == last
    assert item.due_at == ""
    assert controller._mastered.due_items(_ISO) == []
    assert controller._next_review_wall_ts == float("inf")
    assert [e.status for e in controller._daily_log.entries_for(_DAY)] == [
        C.DAILY_LOG_STATUS_REVIEW_OK
    ]


def test_review_lapsed_returns_to_vocab(controller: PetAppController) -> None:
    """「忘了」→ 移出掌握集合、退回生词本、写 review_lapsed 日志。"""

    entry = _entry(4)
    _seed_mastered(controller, entry, stage=2)
    controller._show_word_bubble(0.0)
    assert controller._current_word is not None

    controller._on_review_lapsed()

    assert entry.id not in controller._mastered.ids()
    assert entry.id in {item.id for item in controller._vocab.items()}
    assert controller._current_word is None
    assert controller._reviewing is False
    assert [e.status for e in controller._daily_log.entries_for(_DAY)] == [
        C.DAILY_LOG_STATUS_REVIEW_LAPSED
    ]
    assert controller._next_review_wall_ts == float("inf")


# --------------------------------------------------------------------------- #
# 5. 超时顺延
# --------------------------------------------------------------------------- #
def test_review_timeout_postpones_without_penalty(controller: PetAppController) -> None:
    """超时：不算遗忘、不推进阶段、不写日志，due 顺延 1 小时。"""

    entry = _entry(3)
    _seed_mastered(controller, entry, stage=2)
    controller._show_word_bubble(0.0)
    assert controller._reviewing is True

    controller._postpone_review(now=10.0)

    item = controller._mastered.get(entry.id)
    assert item is not None
    assert item.stage == 2  # 阶段不动
    assert item.review_count == 0  # 不计数
    assert item.due_at == _iso_shift(_ISO, hours=C.REVIEW_TIMEOUT_POSTPONE_HOURS)
    assert entry.id in controller._mastered.ids()
    assert controller._daily_log.count_for(_DAY) == 0  # 不写日志
    assert controller._current_word is None
    assert controller._reviewing is False


def test_frame_timeout_routes_to_postpone_when_reviewing(
    controller: PetAppController,
) -> None:
    """帧循环超时路径按 ``_reviewing`` 分流：复习走顺延而非「未处理」。"""

    entry = _entry(2)
    _seed_mastered(controller, entry, stage=1)
    controller._show_word_bubble(0.0)
    controller._word_deadline = 5.0  # 人为把 deadline 拨到过去

    controller._on_frame_tick(now=6.0)

    item = controller._mastered.get(entry.id)
    assert item is not None
    assert item.stage == 1
    assert controller._daily_log.count_for(_DAY) == 0
    assert controller._current_word is None


# --------------------------------------------------------------------------- #
# 6. 复习态双击 = 偷看答案
# --------------------------------------------------------------------------- #
def test_double_click_during_review_peeks_without_disposing(
    controller: PetAppController,
) -> None:
    """复习泡泡双击：打开详情但不断复习（当前词保持、无日志、按钮条仍在）。"""

    entry = _entry(11)
    _seed_mastered(controller, entry, stage=0)
    controller._show_word_bubble(0.0)

    controller._on_bubble_word_detail(entry)

    assert controller._detail_window is not None  # 详情已打开（可偷看）
    assert controller._current_word is not None  # 复习未被处置
    assert controller._current_word.id == entry.id
    assert controller._reviewing is True
    assert controller._daily_log.count_for(_DAY) == 0


# --------------------------------------------------------------------------- #
# 8. 复习上限：配置收敛 + 托盘档位处理器
# --------------------------------------------------------------------------- #
def test_review_limit_config_default_and_coerce() -> None:
    """默认 20；越界值收敛回档位（999 → 20），合法档位原样通过。"""

    from desktop_pet.core.config import AppConfig

    assert AppConfig().jp_review_daily_limit == 20
    assert AppConfig.from_dict({}).jp_review_daily_limit == 20
    assert AppConfig.from_dict({"jp_review_daily_limit": 999}).jp_review_daily_limit == 20
    assert AppConfig.from_dict({"jp_review_daily_limit": 30}).jp_review_daily_limit == 30


def test_review_limit_tray_handler_persists_and_resets_notify(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """托盘档位 → 写配置 + 同步勾选 + 复位一次性通知标志；非法档位忽略。"""

    controller._review_done_notified = True
    checked: list[int] = []
    monkeypatch.setattr(
        controller._tray, "set_jp_review_limit_checked", lambda v: checked.append(v)
    )

    controller._on_jp_review_limit_selected(30)
    assert controller._cfg.jp_review_daily_limit == 30
    assert controller._review_done_notified is False  # 调大上限 → 允许再次弹出
    assert checked == [30]

    controller._on_jp_review_limit_selected(7)
    assert controller._cfg.jp_review_daily_limit == 30
    assert checked == [30]


# --------------------------------------------------------------------------- #
# 7. v1 → v2 迁移
# --------------------------------------------------------------------------- #
def test_migrate_mastered_review_backfills_due(controller: PetAppController, tmp_path: Path) -> None:
    """v1 记录（无 SRS 字段）→ 迁移后补首轮排期（due = 现在 + 1 天）。"""

    path = tmp_path / "mastered_v1.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "items": [
                    {
                        "id": "n5-0001",
                        "level": "N5",
                        "word": "語1",
                        "kana": "かな",
                        "translation": "译",
                        "mastered_at": _ISO,
                    },
                    {
                        "id": "n5-0002",
                        "level": "N5",
                        "word": "語2",
                        "kana": "かな",
                        "translation": "译",
                        "mastered_at": _ISO,
                        # 已有排期的记录不被迁移改动
                        "stage": 2,
                        "due_at": "2030-01-01T00:00:00Z",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = MasteredStore(path)
    store.load()
    controller._mastered = store

    controller._migrate_mastered_review()

    first = store.get("n5-0001")
    second = store.get("n5-0002")
    assert first is not None and second is not None
    assert first.due_at == _iso_shift(_ISO, days=C.REVIEW_INTERVALS_DAYS[0])
    assert second.due_at == "2030-01-01T00:00:00Z"  # 幂等：已有排期不动
    # 最早排期取两者较小者（2025-01-02 < 2030-01-01）
    assert controller._next_review_wall_ts == _iso_to_wall(first.due_at)
