"""QA（严过关）B 版独立补强边界测试 —— 证明而非轻信工程师自测。

针对工程师既有测试可能漏掉 / 断言偏弱 / 未覆盖的 B 版边界，独立补写：
随机补写：
1. 档位收敛：旧值（字符串 / 整数浮点）→ 默认档位，非 int（bool/字符串）→ 默认。
2. 立即显示（方案 A）：被上限 / 全掌握 / 睡觉 / 气泡关 / 学习关守卫拦截时不弹。
   以及「当前词在展示 → 先落未处理 → 恰好触及上限 → 不再弹新词」的边界。
3. 中文详情查找顺序：打包库优先 → 用户缓存补充（`_lookup_word_detail`）。
4. 详情窗口：关闭后 `_on_worker_failed` 守卫、信号 disconnect 后 worker 不再回调、
   重开复位、无 Key 离线降级。
5. 托盘删除旧项：`jp_add_vocab_requested` / `JP_MENU_ADD_VOCAB` / `set_jp_current_word` /
   `_on_jp_add_vocab` 彻底不存在。
6. `WordBank.entry_by_id` 与生词本双击兜底 `VocabEntry(romaji="")`。

全部只读不改源码；新增文件，不修改工程师既有测试。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig, ConfigStore
from desktop_pet.core.constants import Mood
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker
from desktop_pet.core.word_detail import Example, WordDetail
from desktop_pet.core.word_detail_bank import WordDetailBank
from desktop_pet.core.word_details_cache_store import WordDetailsCacheStore
from desktop_pet.ui.tray import TrayController
from desktop_pet.ui.word_detail_window import WordDetailWindow
from desktop_pet.ui.word_detail_worker import WordDetailNetConfig


def _entry(i: int = 1, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}", level=level, word=f"語{i}",
        kana="かな", translation="译", meaning="义",
    )


def _log_entry(i: int, status: str, day: str = "2025-01-01") -> DailyLogEntry:
    return DailyLogEntry.from_entry(_entry(i), f"{day}T00:00:0{i}Z", status)


def _detail(meaning: str = "我") -> WordDetail:
    return WordDetail(
        meaning_zh=(meaning,),
        pos_zh=("代词",),
        examples=(Example("私は学生です。", "我是学生。"),),
        usage_note_zh="正式、通用。",
    )


# --------------------------------------------------------------------------- #
# 1. 档位收敛边界（旧值 / 字符串 / 整数浮点 / 非 int）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("45", C.JP_BUBBLE_DURATION_S),   # 旧值字符串 → 默认 30
        ("2", C.JP_BUBBLE_DURATION_S),    # 旧值字符串 → 默认 30
        ("300", C.JP_BUBBLE_DURATION_S),  # 旧值字符串 → 默认 30
        ("15", 15),                        # 合法字符串档位
        ("60", 60),
        (45.0, C.JP_BUBBLE_DURATION_S),   # 整数浮点旧值 → 默认 30
        (300.0, C.JP_BUBBLE_DURATION_S),
        (True, C.JP_BUBBLE_DURATION_S),   # bool 非法 → 默认
        (None, C.JP_BUBBLE_DURATION_S),
    ],
)
def test_duration_tier_string_float_edge(raw, expected) -> None:
    cfg = AppConfig.from_dict({"jp_bubble_duration_s": raw})
    assert cfg.jp_bubble_duration_s == expected
    assert isinstance(cfg.jp_bubble_duration_s, int)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("7", C.JP_DAILY_LIMIT),       # 旧值字符串 → 默认 15
        ("200", C.JP_DAILY_LIMIT),     # 旧值字符串 → 默认 15
        ("2", C.JP_DAILY_LIMIT),
        ("20", 20),                     # 合法字符串档位
        ("30", 30),
        (7.0, C.JP_DAILY_LIMIT),       # 整数浮点旧值 → 默认 15
        (200.0, C.JP_DAILY_LIMIT),
        (False, C.JP_DAILY_LIMIT),     # bool 非法 → 默认
        (None, C.JP_DAILY_LIMIT),
    ],
)
def test_daily_limit_tier_string_float_edge(raw, expected) -> None:
    cfg = AppConfig.from_dict({"jp_daily_limit": raw})
    assert cfg.jp_daily_limit == expected
    assert isinstance(cfg.jp_daily_limit, int)


# --------------------------------------------------------------------------- #
# 2. controller 级无头边界（立即显示方案 A 的守卫与极限）
# --------------------------------------------------------------------------- #
@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """构造最小 controller（store 全部指向 tmp_path，注入 3 词小词库）。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.jp_enabled = True
    ctrl._cfg.bubble_enabled = True
    ctrl._cfg.jp_level = "N5"
    ctrl._cfg.jp_daily_limit = 5
    ctrl._cfg.jp_bubble_duration_s = 30

    # 6 词小词库：足以覆盖「4 条已展示 + 当前词 + 潜在新词」的极限边界
    entries = tuple(_entry(i) for i in range(1, 7))
    ctrl._bank = WordBank(entries)
    ctrl._picker = WeightedWordPicker(ctrl._bank, random.Random(0))

    ctrl._mastered = MasteredStore(tmp_path / "mastered.json")
    ctrl._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    ctrl._vocab = VocabStore(tmp_path / "vocab.json")
    ctrl._mastered.load()
    ctrl._daily_log.load()
    ctrl._vocab.load()

    ctrl._detail_cache = WordDetailsCacheStore(tmp_path / "word_details_cache.json")
    ctrl._detail_cache.load()
    ctrl._detail_bank = WordDetailBank.empty()

    ctrl._today_str = "2025-01-01"
    ctrl._last_bubble_ts = float("-inf")
    ctrl._today_done_notified = False
    return ctrl


def test_show_now_noop_when_jp_disabled(controller: PetAppController) -> None:
    controller._cfg.jp_enabled = False
    controller._on_jp_show_now()
    assert controller._current_word is None


def test_show_now_blocked_by_bubble_off(controller: PetAppController) -> None:
    controller._cfg.bubble_enabled = False
    controller._on_jp_show_now()
    assert controller._current_word is None


def test_show_now_blocked_by_sleep(controller: PetAppController) -> None:
    controller._sm._state = Mood.SLEEP
    controller._on_jp_show_now()
    assert controller._current_word is None


def test_show_now_blocked_by_limit_notifies(controller: PetAppController) -> None:
    for i in range(1, 6):  # limit = 5 → 已满
        controller._daily_log.add_entry(
            "2025-01-01", _log_entry(i, C.DAILY_LOG_STATUS_UNPROCESSED)
        )
    controller._today_done_notified = False
    controller._on_jp_show_now()
    assert controller._current_word is None
    assert controller._today_done_notified is True  # 已给「今日完成」通知


def test_show_now_not_blocked_by_all_mastered(controller: PetAppController) -> None:
    """当日已展示词全部点了掌握，也不应拦截「立即显示」——仅每日上限才是硬停止。

    回归：曾因 `_jp_stop_for_today` 混入 `all_mastered`，点一次「记住了」就误停当天。
    """

    controller._daily_log.add_entry("2025-01-01", _log_entry(1, C.DAILY_LOG_STATUS_MASTERED))
    controller._daily_log.add_entry("2025-01-01", _log_entry(2, C.DAILY_LOG_STATUS_MASTERED))
    controller._today_done_notified = False
    controller._on_jp_show_now()
    assert controller._current_word is not None
    assert controller._today_done_notified is False


def test_show_now_dispose_then_hit_limit_no_new_word(controller: PetAppController) -> None:
    """当前词在展示 + count=limit-1：立即显示先落未处理触及上限，不再弹新词。"""

    for i in range(1, 5):  # 4 条，limit=5 未满
        controller._daily_log.add_entry(
            "2025-01-01", _log_entry(i, C.DAILY_LOG_STATUS_UNPROCESSED)
        )
    controller._show_word_bubble(0.0)
    first = controller._current_word
    assert first is not None

    controller._on_jp_show_now()

    # 当前词被先落「未处理」（count 4→5 触顶），随后 _show_word_bubble 被上限拦截
    assert controller._current_word is None
    assert controller._daily_log.count_for("2025-01-01") == 5
    assert controller._daily_log.unprocessed_count_for("2025-01-01") == 5


def test_show_now_happy_path_disposes_and_shows(controller: PetAppController) -> None:
    """独立复证方案 A 主路径：当前词落未处理后，绕过最小间隔弹新词。"""

    controller._show_word_bubble(0.0)
    first = controller._current_word
    assert first is not None
    assert controller._daily_log.count_for("2025-01-01") == 0

    controller._on_jp_show_now()

    assert controller._current_word is not None
    assert controller._current_word.id != first.id
    assert controller._daily_log.count_for("2025-01-01") == 1
    assert controller._daily_log.unprocessed_count_for("2025-01-01") == 1


# --------------------------------------------------------------------------- #
# 3. 中文详情查找顺序：打包库优先 → 用户缓存补充（app 层 `_lookup_word_detail`）
# --------------------------------------------------------------------------- #
def test_detail_bank_precedes_cache(controller: PetAppController) -> None:
    bank_detail = _detail("库")
    cache_detail = _detail("缓存")
    controller._detail_bank = WordDetailBank({"n5-0001": bank_detail})
    controller._detail_cache.put("n5-0001", cache_detail, controller._now_iso())

    detail, source = controller._lookup_word_detail("n5-0001")
    assert detail == bank_detail        # 打包库权威优先，不被旧缓存遮挡
    assert source == C.WORD_DETAIL_SOURCE_LOCAL


def test_detail_cache_used_when_bank_misses(controller: PetAppController) -> None:
    cache_detail = _detail("缓存")
    controller._detail_bank = WordDetailBank.empty()
    controller._detail_cache.put("n5-0001", cache_detail, controller._now_iso())

    detail, source = controller._lookup_word_detail("n5-0001")
    assert detail == cache_detail
    assert source == C.WORD_DETAIL_SOURCE_CACHE


def test_detail_lookup_miss_returns_none(controller: PetAppController) -> None:
    controller._detail_bank = WordDetailBank.empty()
    assert controller._lookup_word_detail("n5-0001") == (None, None)
    assert controller._lookup_word_detail("") == (None, None)


def test_detail_bank_empty_content_treated_as_miss(controller: PetAppController) -> None:
    controller._detail_bank = WordDetailBank({"n5-0001": WordDetail()})
    assert controller._lookup_word_detail("n5-0001") == (None, None)


# --------------------------------------------------------------------------- #
# 4. 详情窗口：关闭守卫 / 信号断开 / 重开复位 / 离线降级
# --------------------------------------------------------------------------- #
def _detail_entry() -> VocabEntry:
    return VocabEntry(
        id="n5-0001", level="N5", word="食べる", kana="たべる",
        translation="吃", meaning="进食", romaji="taberu",
    )


def _net(api_key: str = "sk-test") -> WordDetailNetConfig:
    return WordDetailNetConfig(
        api_key=api_key, base_url=C.LLM_ENDPOINT, model=C.LLM_MODEL,
        timeout_s=C.LLM_TIMEOUT_S, retries=C.LLM_RETRIES,
    )


class _FakePool:
    def __init__(self) -> None:
        self.started: list[object] = []
        self.cleared: bool = False

    def start(self, runnable: object) -> None:
        self.started.append(runnable)

    def clear(self) -> None:
        self.cleared = True


def test_close_guards_failed_callback(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_detail_entry(), detail=None, net=_net())

    window.close()
    emitted: list[tuple[str, str]] = []
    window.detail_failed.connect(lambda item_id, msg: emitted.append((item_id, msg)))
    window._on_worker_failed("n5-0001", "boom")
    assert emitted == []  # _closed 守卫拦截失败回调


def test_close_disconnects_worker_signals(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_detail_entry(), detail=None, net=_net())
    worker = pool.started[0]  # 真实 WordDetailWorker（含真实 WordDetailSignals）

    succeeded: list[str] = []
    window.detail_succeeded.connect(lambda item_id, _d: succeeded.append(item_id))

    window.close()  # closeEvent 会 disconnect worker.signals + 置 _closed

    worker.signals.succeeded.emit("n5-0001", _detail())
    assert succeeded == []  # 信号已断开，回调未达窗口


def test_reopen_resets_closed_and_restarts_worker(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    window.show_entry(_detail_entry(), detail=None, net=_net())
    window.close()
    assert window._closed is True
    assert pool.cleared is True

    window.show_entry(_detail_entry(), detail=None, net=_net())
    assert window._closed is False
    assert len(pool.started) == 2  # 重开重新发一次查询


def test_offline_hint_when_no_key(qtbot) -> None:
    pool = _FakePool()
    window = WordDetailWindow(pool=pool)
    qtbot.addWidget(window)
    online = _net()
    offline = WordDetailNetConfig("", online.base_url, online.model, online.timeout_s, 0)

    window.show_entry(_detail_entry(), detail=None, net=offline)

    assert pool.started == []  # 无 Key → 不发请求
    assert window._status_label.text() == C.WORD_DETAIL_OFFLINE_HINT
    assert window._retry_btn.isHidden() is False
    assert "Jisho" not in window._status_label.text()


# --------------------------------------------------------------------------- #
# 5. 托盘删除旧项（静态断言）
# --------------------------------------------------------------------------- #
def test_tray_removed_add_vocab_signal_and_methods() -> None:
    assert not hasattr(TrayController, "jp_add_vocab_requested")
    assert not hasattr(TrayController, "set_jp_current_word")


def test_constants_removed_add_vocab_menu() -> None:
    assert not hasattr(C, "JP_MENU_ADD_VOCAB")
    assert not hasattr(C, "JP_MENU_ADD_VOCAB_TEMPLATE")


def test_controller_removed_add_vocab_slot() -> None:
    assert not hasattr(PetAppController, "_on_jp_add_vocab")


def test_tray_source_has_no_add_vocab_menu_label() -> None:
    import desktop_pet.ui.tray as tray_mod

    src = Path(tray_mod.__file__).read_text(encoding="utf-8")
    assert "加入生词本" not in src  # 旧菜单项文案彻底移除


# --------------------------------------------------------------------------- #
# 6. WordBank.entry_by_id 与生词本双击兜底
# --------------------------------------------------------------------------- #
def test_entry_by_id_found_and_missing() -> None:
    bank = WordBank((_entry(1), _entry(2)))
    assert bank.entry_by_id("n5-0001") is not None
    assert bank.entry_by_id("n5-0001").word == "語1"
    assert bank.entry_by_id("n5-9999") is None
    assert bank.entry_by_id("") is None


def test_vocab_double_click_fallback_romaji_empty(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, VocabEntry] = {}
    monkeypatch.setattr(
        controller, "_open_word_detail", lambda e: captured.setdefault("entry", e)
    )
    # 词库内没有该 id（只有 語1..語3），生词本里有一条快照 → 走兜底
    fallback = VocabEntry(
        id="n5-9999", level="N5", word="猫", kana="ねこ",
        translation="猫", meaning="动物", romaji="",
    )
    controller._vocab.add(fallback, "2025-01-01T00:00:00Z")

    controller._on_vocab_word_double_clicked("n5-9999")

    entry = captured.get("entry")
    assert entry is not None
    assert entry.id == "n5-9999"
    assert entry.word == "猫"
    assert entry.romaji == ""  # 兜底构造 romaji 恒为空
