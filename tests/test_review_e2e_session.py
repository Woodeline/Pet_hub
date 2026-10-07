"""工程师自测：记忆曲线端到端会话 —— 驱动**真实帧循环**模拟多日学习闭环。

与 test_review_scheduler.py 的单方法直调不同，本文件把 controller 当黑盒：
只拨模拟时钟（墙钟 / ISO / 本地日 / monotonic 四者联动）并反复调
``_on_frame_tick``，验证完整行为链路：

1. **全阶梯毕业会话**：新词展示 → 点「记住了」→ 此后 7 天按阶梯逐轮弹出复习
   （唤醒 → 复习优先）→ 每轮「还记得」→ 第 7 轮毕业（due 清空、排期归 inf）。
2. **配额口径**：复习处置写日志但**不占新词配额**（``new_word_count_for``）——
   连续 6 轮复习后新词照常展示；纯复习日不挡新词。
3. **遗忘回炉**：复习「忘了」→ 退回生词本 → 次日作为生词（加权）再次展示 →
   再「记住了」→ SRS 从 stage 0 重新爬梯。
4. **超时-再考**：复习泡泡不作答超时 → 无痕顺延 1h → 到点再次弹出同一词。
5. **重启续期**：掌握/复习状态落盘后，新 controller 实例（模拟重启）加载后
   排期不变，迁移幂等（不重写已有 due）。
6. **窗口驱动操作**：已掌握词库窗口「立即复习」（未来的词也能手动考）、
   「退回生词本」信号端到端，且操作后窗口即时刷新。

测试纪律（吸取虚拟时钟教训）：墙钟（``_wall_now``）、ISO（``_now_iso``）、本地日
（``_local_date_str``）全部注入 :class:`_SimClock` 替身，monotonic 走 ``t`` 通道；
情绪气泡窗口置 inf 以隔离无关路径。offscreen 渲染。
"""

from __future__ import annotations

import random
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController, _iso_to_wall
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker
from desktop_pet.core.word_detail_bank import WordDetailBank
from desktop_pet.core.word_details_cache_store import WordDetailsCacheStore

_ISO_FMT = "%Y-%m-%dT%H:%M:%SZ"


class _SimClock:
    """四通道联动模拟时钟：``wall``（墙钟秒）为基准，其余派生。

    ``iso`` / ``day`` 按 wall 派生，保证「ISO 字典序 = 时间序」「跨日 rollover」
    与真实运行同构；``t`` 是 monotonic 通道（帧循环入参）。
    """

    def __init__(self) -> None:
        # 锚定当日 UTC 06:00（而非真实 now）：测试步进最多快进数小时，
        # 距午夜余量 >6h，「day 在测试中途跨日」的抖动不再随机出现
        # （真实 now 若落在 23:xx，6×700s 的步进会恰好滚过午夜，day 变化
        # 而测试前置捕获的 day 不变 → 偶发失败）。
        now_dt = datetime.now(timezone.utc)
        anchored = now_dt.replace(hour=6, minute=0, second=0, microsecond=0)
        self.wall: float = anchored.timestamp()
        self.t: float = 1000.0

    @property
    def iso(self) -> str:
        return datetime.fromtimestamp(self.wall, timezone.utc).strftime(_ISO_FMT)

    @property
    def day(self) -> str:
        return f"sim-{int(self.wall // 86400)}"


def _entry(i: int, level: str = "N5") -> VocabEntry:
    return VocabEntry(
        id=f"{level.lower()}-{i:04d}",
        level=level,
        word=f"語{i}",
        kana="かな",
        translation="译",
        meaning="义",
    )


def _make_controller(qapp: QApplication, tmp_path: Path, clock: _SimClock) -> PetAppController:
    """构造最小 controller（同 test_jp_detail_mastered 范式）+ 全时钟替身。"""

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

    # —— 时钟替身：四通道全部注入 ——
    ctrl._now_iso = lambda: clock.iso
    ctrl._wall_now = lambda: clock.wall
    ctrl._local_date_str = lambda: clock.day
    ctrl._today_str = clock.day
    # 隔离无关路径：情绪气泡两个节奏窗口永久关闭（复习/新词链路不受影响）
    ctrl._next_bubble_ts = float("inf")
    ctrl._next_kb_bubble_ts = float("inf")
    ctrl._last_bubble_ts = float("-inf")
    ctrl._next_review_wall_ts = float("inf")
    # monotonic 通道不模拟：锚定到 controller 构造时的真实 monotonic（与 _sm 同锚）。
    # 这样 _on_review_ok / _on_word_mastered 等按钮处理器内部读 time.monotonic()
    # 与模拟 t 天然同通道（教训：虚拟时钟必须锚定 _sm 时钟，否则排期被写飞）。
    clock.t = time.monotonic() + 5.0
    return ctrl


@pytest.fixture()
def clock() -> _SimClock:
    return _SimClock()


@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path, clock: _SimClock) -> PetAppController:
    return _make_controller(qapp, tmp_path, clock)


def _seed_due(ctrl: PetAppController, entry: VocabEntry, stage: int, *, overdue_s: float) -> str:
    """把词条种入掌握集合，due 恒定在「当前模拟时刻 - overdue_s」。"""

    from desktop_pet.core.mastered_store import MasteredItem

    due = datetime.fromtimestamp(
        ctrl._wall_now() - overdue_s, timezone.utc
    ).strftime(_ISO_FMT)
    ctrl._mastered._items.append(
        MasteredItem(
            id=entry.id, level=entry.level, word=entry.word, kana=entry.kana,
            translation=entry.translation, mastered_at=due, stage=stage,
            due_at=due, last_review_at=due, review_count=stage,
        )
    )
    ctrl._mastered.save()
    ctrl._refresh_review_schedule()
    return due


def _tick(ctrl: PetAppController, clock: _SimClock, step_s: float = 60.0) -> None:
    """推进一个帧循环节拍：先敲键（防入睡），再走一帧。"""

    clock.t += step_s
    clock.wall += step_s
    ctrl._sm.on_keystroke(clock.t, False)
    ctrl._on_frame_tick(now=clock.t)


def _run_to(ctrl: PetAppController, clock: _SimClock, wall_target: float) -> None:
    """把模拟时钟快进到 wall_target（跨日自动触发帧循环内的 rollover）再走一帧。"""

    assert wall_target > clock.wall
    clock.t += wall_target - clock.wall + 60.0
    clock.wall = wall_target + 60.0
    ctrl._sm.on_keystroke(clock.t, False)
    ctrl._on_frame_tick(now=clock.t)


# --------------------------------------------------------------------------- #
# 1. 全阶梯毕业会话（真实帧循环驱动）
# --------------------------------------------------------------------------- #
def test_full_ladder_graduation_session(controller: PetAppController, clock: _SimClock) -> None:
    """掌握 → 7 轮按阶梯复习 → 毕业：全程只依赖帧循环与按钮处置。"""

    # 第 0 天：展示新词并掌握
    controller._next_word_ts = clock.t
    _tick(controller, clock)
    word = controller._current_word
    assert word is not None and controller._reviewing is False
    controller._on_word_mastered()

    item = controller._mastered.get(word.id)
    assert item is not None and item.stage == 0
    due_wall = _iso_to_wall(item.due_at)

    total = len(C.REVIEW_INTERVALS_DAYS)
    for stage in range(total):
        # 快进到 due 之后的下一个单词槽 → 唤醒 → 复习优先弹出
        _run_to(controller, clock, due_wall + 120.0)
        assert controller._current_word is not None, f"第 {stage + 1} 轮复习未弹出"
        assert controller._current_word.id == word.id
        assert controller._reviewing is True
        # 泡泡是主动回忆形态
        assert controller._bubble._line_translation == ""

        controller._on_review_ok()
        item = controller._mastered.get(word.id)
        if stage < total - 1:
            assert item.stage == stage + 1
            assert item.review_count == stage + 1
            # 下轮 due = 本轮复习时刻 + 阶梯间隔
            expected_days = C.REVIEW_INTERVALS_DAYS[stage + 1]
            delta = _iso_to_wall(item.due_at) - (clock.wall - 60.0)
            assert 0 < delta <= expected_days * 86400 + 120
            due_wall = _iso_to_wall(item.due_at)
        else:
            assert item.stage == total and item.due_at == ""

    # 毕业后：不再排期、不再弹出
    assert controller._mastered.earliest_due_iso() == ""
    assert controller._next_review_wall_ts == float("inf")
    _run_to(controller, clock, clock.wall + 7 * 86400)
    assert controller._current_word is None or controller._current_word.id != word.id


# --------------------------------------------------------------------------- #
# 2. 配额口径：复习不占新词配额
# --------------------------------------------------------------------------- #
def test_reviews_do_not_consume_new_word_quota(
    controller: PetAppController, clock: _SimClock
) -> None:
    """连续 6 轮复习（超每日上限 5）后，新词仍照常展示。"""

    # 20 词词库：6 个复习词会被「已掌握 ∪ 当日已展示」双重排除，
    # 剩余 14 个才是新词候选池（顺带验证排除集语义）
    controller._bank = WordBank(tuple(_entry(i) for i in range(1, 21)))
    controller._picker = WeightedWordPicker(controller._bank, controller._rng)
    entries = [_entry(i) for i in range(1, 7)]
    for k, e in enumerate(entries):
        _seed_due(controller, e, stage=0, overdue_s=3600.0 * (k + 1))

    day = clock.day
    for _ in range(6):
        # 700s 步长：稳跨复习节奏门控（处置后强制 30~600s），每拍弹出一条复习
        _tick(controller, clock, 700.0)
        assert controller._reviewing is True
        controller._on_review_ok()

    assert controller._daily_log.count_for(day) == 6
    # 核心：新词配额未被复习侵蚀
    assert controller._daily_log.new_word_count_for(day) == 0
    assert controller._jp_stop_for_today() is False

    # 复习清空后的下一个槽：新词照常出现（步长跨过 30~600s 重排期窗口）
    _tick(controller, clock, 700.0)
    assert controller._current_word is not None
    assert controller._reviewing is False
    assert controller._current_word.id not in {e.id for e in entries}


# --------------------------------------------------------------------------- #
# 3. 遗忘 → 回炉重学 → SRS 重置
# --------------------------------------------------------------------------- #
def test_lapse_then_relearn_resets_stage(
    controller: PetAppController, clock: _SimClock, tmp_path: Path
) -> None:
    """「忘了」→ 退回生词本 → 次日加权再展示 → 再掌握 → stage 从 0 重来。"""

    entry = _entry(1)
    # 单词词库：次日重学必然抽中（vocab 加权 ×3）
    controller._bank = WordBank((entry,))
    controller._picker = WeightedWordPicker(controller._bank, controller._rng)

    _seed_due(controller, entry, stage=2, overdue_s=3600.0)
    _tick(controller, clock)
    assert controller._reviewing is True

    controller._on_review_lapsed()
    assert entry.id not in controller._mastered.ids()
    assert entry.id in {i.id for i in controller._vocab.items()}
    assert controller._daily_log.entries_for(clock.day)[0].status == C.DAILY_LOG_STATUS_REVIEW_LAPSED

    # 次日（新 day key → 当日排除集清空）：作为生词再次展示（步长跨节奏门控）
    clock.wall += 86400
    _tick(controller, clock, 700.0)
    assert controller._current_word is not None
    assert controller._current_word.id == entry.id
    assert controller._reviewing is False

    controller._on_word_mastered()
    item = controller._mastered.get(entry.id)
    assert item is not None
    assert item.stage == 0  # SRS 重置，从首轮重新爬梯
    assert item.due_at != ""
    # 掌握处置同步移出生词本
    assert entry.id not in {i.id for i in controller._vocab.items()}


# --------------------------------------------------------------------------- #
# 4. 超时顺延后再考
# --------------------------------------------------------------------------- #
def test_review_timeout_then_reshown(controller: PetAppController, clock: _SimClock) -> None:
    """不作答超时 → 顺延 1h（不计遗忘）→ 到点再次弹出同一词。"""

    entry = _entry(5)
    _seed_due(controller, entry, stage=1, overdue_s=3600.0)
    _tick(controller, clock)
    assert controller._reviewing is True
    stage_before = controller._mastered.get(entry.id)

    # 超时（deadline 过后一帧）：无痕顺延（deadline 是 monotonic，换算墙钟目标）
    deadline_wall = clock.wall + (controller._word_deadline - clock.t)
    _run_to(controller, clock, deadline_wall + 5.0)
    item = controller._mastered.get(entry.id)
    before = stage_before
    assert controller._current_word is None
    # 无痕顺延：阶段 / 复习计数 / 最近复习时间三字段全部原样
    assert item.stage == before.stage
    assert item.review_count == before.review_count
    assert item.last_review_at == before.last_review_at
    assert controller._daily_log.count_for(clock.day) == 0
    postponed_due = item.due_at

    # 顺延到期 → 再次弹出同一词
    _run_to(controller, clock, _iso_to_wall(postponed_due) + 120.0)
    assert controller._current_word is not None
    assert controller._current_word.id == entry.id
    assert controller._reviewing is True


# --------------------------------------------------------------------------- #
# 5. 重启续期 + 迁移幂等
# --------------------------------------------------------------------------- #
def test_restart_preserves_srs_state(
    qapp: QApplication, tmp_path: Path, clock: _SimClock
) -> None:
    """新 controller 实例（模拟重启）加载同一 mastered.json：排期原样恢复。"""

    ctrl1 = _make_controller(qapp, tmp_path, clock)
    entry = _entry(7)
    due = datetime.fromtimestamp(
        clock.wall + 3 * 86400, timezone.utc
    ).strftime(_ISO_FMT)
    ctrl1._mastered.add(entry, clock.iso, stage=1, due_at=due)
    ctrl1._refresh_review_schedule()
    assert ctrl1._next_review_wall_ts == _iso_to_wall(due)

    # —— 重启：全新时钟 + 全新 controller，同 tmp 路径 ——
    clock2 = _SimClock()
    ctrl2 = _make_controller(qapp, tmp_path, clock2)
    ctrl2._migrate_mastered_review()  # start() 中的迁移步骤

    item = ctrl2._mastered.get(entry.id)
    assert item is not None
    assert (item.stage, item.due_at) == (1, due)  # 已有排期不被迁移改写（幂等）
    assert ctrl2._next_review_wall_ts == _iso_to_wall(due)

    ctrl2._migrate_mastered_review()  # 再跑一次仍幂等
    assert ctrl2._mastered.get(entry.id).due_at == due


# --------------------------------------------------------------------------- #
# 6. 复习节奏门控：处置后强制一拍，不再连环轰炸
# --------------------------------------------------------------------------- #
def test_dispose_sets_review_pacing(controller: PetAppController, clock: _SimClock) -> None:
    """复习处置后 ``_next_review_ts`` 落在 [now+30, now+600] 区间（与生词同款节奏）。"""

    import time as _time

    entry = _entry(6)
    _seed_due(controller, entry, stage=0, overdue_s=3600.0)
    _tick(controller, clock)
    assert controller._reviewing is True

    before = _time.monotonic()
    controller._on_review_ok()
    pacing = controller._next_review_ts
    assert before + C.JP_WORD_MIN_INTERVAL_S <= pacing
    assert pacing <= before + C.JP_WORD_MAX_INTERVAL_S + 1.0


def test_reviews_paced_not_cascaded(controller: PetAppController, clock: _SimClock) -> None:
    """两条到期复习：第一条答完、节奏未到时第二条**不得**顶上；到点后恢复。"""

    e1, e2 = _entry(1), _entry(2)
    _seed_due(controller, e1, stage=0, overdue_s=7200.0)
    _seed_due(controller, e2, stage=0, overdue_s=3600.0)

    _tick(controller, clock)
    assert controller._reviewing is True and controller._current_word.id == e1.id
    controller._on_review_ok()

    # 人为把节奏门控拨到未来（等价于「刚答完不到半分钟」）
    controller._next_review_ts = clock.t + 300.0
    _tick(controller, clock, 60.0)
    assert controller._reviewing is False
    assert controller._current_word is None or controller._current_word.id != e2.id

    # 门控放开后的下一拍：第二条复习正常弹出
    for _ in range(3):
        _tick(controller, clock, 700.0)
        if controller._reviewing:
            break
    assert controller._reviewing is True
    assert controller._current_word.id == e2.id


# --------------------------------------------------------------------------- #
# 7. 每日复习上限：作答数达上限 → 一次性通知 + 停止自动弹；调大档位恢复
# --------------------------------------------------------------------------- #
def test_review_daily_limit_caps_session(
    controller: PetAppController, clock: _SimClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上限 2：答完两条后第三条不再自动弹（通知一次）；上限调到 50 后恢复。"""

    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))
    controller._cfg.jp_review_daily_limit = 2

    # 三词词库：新词候选恰好被复习词占满，隔离「让位新词」的干扰
    words = [_entry(i) for i in range(1, 4)]
    controller._bank = WordBank(tuple(words))
    controller._picker = WeightedWordPicker(controller._bank, controller._rng)
    for k, w in enumerate(words):
        _seed_due(controller, w, stage=0, overdue_s=3600.0 * (k + 1))
    day = clock.day

    # 第 1、2 条：正常弹出并作答
    for _ in range(2):
        _tick(controller, clock, 700.0)
        assert controller._reviewing is True
        controller._on_review_ok()
    assert controller._daily_log.review_count_for(day) == 2

    # 第 3 条：额度用完 → 不弹复习（词库池也空 → 无泡泡），一次性通知
    _tick(controller, clock, 700.0)
    assert controller._reviewing is False
    assert controller._current_word is None  # 池空，新词也无
    assert controller._daily_log.review_count_for(day) == 2  # 额度外不再计数
    assert captured.count(C.JP_NOTIFY_REVIEW_TODAY_DONE) == 1
    # 被拦下的是最早到期、最先弹出两条之外的那条（按 due 升序：words[2]→[1]→[0]）
    assert controller._mastered.get(words[0].id).stage == 0  # 仍到期、明天继续

    # 再走一拍：通知不重复
    _tick(controller, clock, 700.0)
    assert captured.count(C.JP_NOTIFY_REVIEW_TODAY_DONE) == 1

    # 手动「立即复习」不受上限约束
    controller._on_mastered_review_now(words[0].id)
    assert controller._reviewing is True and controller._current_word.id == words[0].id
    controller._on_review_ok()
    assert controller._daily_log.review_count_for(day) == 3

    # 档位调大 → 一次性通知标志复位（虽已超额，语义是「用户主动放宽」）
    controller._on_jp_review_limit_selected(50)
    assert controller._review_done_notified is False


# --------------------------------------------------------------------------- #
# 6. 窗口驱动操作端到端
# --------------------------------------------------------------------------- #
def test_mastered_window_drive_actions(
    controller: PetAppController, clock: _SimClock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """窗口「立即复习」（未到期也能手动考）/「退回生词本」信号端到端 + 即时刷新。"""

    monkeypatch.setattr(
        "desktop_pet.app.controller.show_window_animated", lambda *a, **k: None
    )
    e_future = _entry(2)
    e_due = _entry(3)
    future_due = datetime.fromtimestamp(
        clock.wall + 3 * 86400, timezone.utc
    ).strftime(_ISO_FMT)
    controller._mastered.add(e_future, clock.iso, stage=1, due_at=future_due)
    _seed_due(controller, e_due, stage=0, overdue_s=3600.0)

    controller._on_jp_mastered()
    win = controller._mastered_window
    assert win is not None
    # 展示排序：到期在前、未来在后
    assert list(win._card_by_id.keys()) == ["n5-0003", "n5-0002"]

    # 立即复习「未来」的词：绕过 due，直接弹复习泡泡
    win.review_requested.emit("n5-0002")
    assert controller._current_word is not None
    assert controller._current_word.id == "n5-0002"
    assert controller._reviewing is True

    controller._on_review_ok()
    assert controller._mastered.get("n5-0002").stage == 2
    # 窗口已即时刷新：状态行展示新阶段（stage 2 → 「记忆阶段 3/7」）
    status = win._card_by_id["n5-0002"].layout().itemAt(2).widget().text()
    assert C.JP_MASTERED_STAGE_TEMPLATE.format(stage=3, total=7) in status

    # 退回生词本：移出掌握集合 + 加入生词本 + 窗口/排期同步
    win.back_to_vocab_requested.emit("n5-0003")
    assert "n5-0003" not in controller._mastered.ids()
    assert "n5-0003" in {i.id for i in controller._vocab.items()}
    assert list(win._card_by_id.keys()) == ["n5-0002"]
    # 剩余唯一排期 = n5-0002 复习后的新 due（+7d），而非种子时的 +3d
    new_due = controller._mastered.get("n5-0002").due_at
    assert controller._next_review_wall_ts == _iso_to_wall(new_due)
