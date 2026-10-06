"""工程师自测：单词详情窗口「记住了」按钮（与气泡按钮复用同一处置逻辑）。

覆盖：
1. 窗口：默认「记住了」可点击；点击携带当前词条发出 ``mastered_clicked``；
   ``set_mastered_state(True)`` → 「已掌握」且禁用；切换到新词条时复位，
   同词条重试（``_on_retry`` 路径）不复位。
2. controller：详情词 = 当前气泡词 → 走 ``_dispose_word`` 完整处置
   （写每日日志 / 清当前词 / 排期下一词）；详情词 ≠ 当前气泡词 → 仅写
   mastered + 托盘反馈，不写每日日志、不影响当前展示词与每日配额；
   重复标记 → 「已经掌握啦」反馈；``_open_word_detail`` 按 mastered 集合
   同步按钮初始态；窗口点击端到端落库。
3. 视觉统一：详情「记住了」按钮取 ``theme`` 的 ``success`` 变体，色值同源
   气泡按钮绿（``SEMANTIC_COLORS["success"] == COLORS["jp_button_primary_bg"]``）。
4. 生词本同步：掌握处置（详情 / 气泡两路径）都把该词移出生词本 + 即时
   ``refresh`` 生词本窗口，反馈文案追加「已移出生词本」后缀；不在生词本时
   文案保持原样（不加后缀）。
5. 闭环：双击气泡（记生词 + 开详情）→ 详情点「记住了」→ 生词本清空、mastered 收录。

全部为新增用例；遵循项目测试隔离约定（配置 / 数据落 tmp_path，offscreen 渲染）。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import VocabEntry, WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker
from desktop_pet.core.word_detail import WordDetail
from desktop_pet.core.word_detail_bank import WordDetailBank
from desktop_pet.core.word_details_cache_store import WordDetailsCacheStore
from desktop_pet.ui import theme
from desktop_pet.ui.word_detail_window import WordDetailWindow

_DAY: str = "2025-01-01"
_LIMIT: int = 5
_ISO: str = "2025-01-01T00:00:00Z"


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


class _FakePool:
    """记录 start/clear，不真正执行 runnable（避免真实联网）。"""

    def __init__(self) -> None:
        self.started: list[object] = []
        self.cleared: bool = False

    def start(self, runnable: object) -> None:
        self.started.append(runnable)

    def clear(self) -> None:
        self.cleared = True


class _FakeVocabWindow:
    """记录 refresh 调用（生词本窗口的鸭子类型替身，避免真实建窗）。"""

    def __init__(self) -> None:
        self.refreshed: list[list[object]] = []

    def refresh(self, items: list[object]) -> None:
        self.refreshed.append(list(items))


@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """构造最小 controller（同 test_jp_quota_decouple 范式）：12 词小词库，数据落 tmp_path。"""

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


# --------------------------------------------------------------------------- #
# 1. 窗口：按钮默认态 / 信号携带词条 / 状态切换 / 复位规则
# --------------------------------------------------------------------------- #
def test_mastered_button_default_clickable_and_emits_entry(qtbot) -> None:
    """默认文案为「记住了」且可点击；点击携带当前词条发出 mastered_clicked。"""

    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    entry = _entry(1)
    window.show_entry(entry, WordDetail(meaning_zh=("义",)), "来源")

    btn = window._mastered_btn
    assert btn.text() == C.JP_BUTTON_MASTERED
    assert btn.isEnabled()

    got: list[VocabEntry] = []
    window.mastered_clicked.connect(got.append)
    btn.click()

    assert got == [entry]


def test_mastered_button_click_without_entry_no_signal(qtbot) -> None:
    """未展示任何词条时点击：不发信号（守卫分支）。"""

    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)

    got: list[VocabEntry] = []
    window.mastered_clicked.connect(got.append)
    window._mastered_btn.click()

    assert got == []


def test_set_mastered_state_toggles_label_and_enabled(qtbot) -> None:
    """set_mastered_state(True) → 「已掌握」禁用；False → 「记住了」恢复。"""

    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    btn = window._mastered_btn

    window.set_mastered_state(True)
    assert btn.text() == C.WORD_DETAIL_MASTERED_DONE
    assert not btn.isEnabled()

    window.set_mastered_state(False)
    assert btn.text() == C.JP_BUTTON_MASTERED
    assert btn.isEnabled()


def test_mastered_button_resets_on_new_entry_keeps_on_retry(qtbot) -> None:
    """切换到新词条 → 复位未掌握态；同词条重试（同 id 再 show_entry）→ 保持原态。"""

    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    btn = window._mastered_btn

    window.show_entry(_entry(1), WordDetail(meaning_zh=("义",)), "来源")
    window.set_mastered_state(True)

    # 新词条 → 复位
    window.show_entry(_entry(2), WordDetail(meaning_zh=("义",)), "来源")
    assert btn.text() == C.JP_BUTTON_MASTERED
    assert btn.isEnabled()

    # 同词条重试路径 → 保持已掌握态
    window.set_mastered_state(True)
    window.show_entry(window._entry, None, None, None)  # _on_retry 的同 id 调用形态
    assert btn.text() == C.WORD_DETAIL_MASTERED_DONE
    assert not btn.isEnabled()


# --------------------------------------------------------------------------- #
# 2. controller：详情「记住了」两路径与气泡按钮行为一致
# --------------------------------------------------------------------------- #
def test_detail_mastered_current_word_full_dispose(controller: PetAppController) -> None:
    """详情词 = 当前气泡词（自动展示）→ 与点气泡按钮完全一致：写 mastered + 每日日志 + 清当前词。"""

    controller._show_word_bubble(0.0)  # 自动路径
    word = controller._current_word
    assert word is not None
    assert controller._word_manual is False

    controller._on_detail_mastered(word)

    assert word.id in controller._mastered.ids()
    # 自动词走完整处置 → 每日日志 +1（与气泡「记住了」同一数据处理）
    assert controller._daily_log.count_for(_DAY) == 1
    assert word.id in controller._daily_log.shown_ids_for(_DAY)
    assert controller._current_word is None


def test_detail_mastered_non_current_word_store_only(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """详情词 ≠ 当前气泡词 → 仅写 mastered + 托盘反馈，不动当前词 / 每日日志。"""

    controller._show_word_bubble(0.0)
    current = controller._current_word
    assert current is not None
    other = _entry(12) if current.id != "n5-0012" else _entry(11)

    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_detail_mastered(other)

    assert other.id in controller._mastered.ids()
    assert C.JP_NOTIFY_MASTERED_ADDED.format(word=other.word, kana=other.kana) in captured
    # 不写每日日志（不占用每日配额，口径同手动词「记住了」决策 D1）
    assert controller._daily_log.count_for(_DAY) == 0
    # 当前展示词不受牵连（不隐藏气泡 / 不排期下一词）
    assert controller._current_word is current


def test_detail_mastered_without_current_word(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无气泡展示时（学习记录 / 生词本打开详情）→ 仅写 mastered + 托盘反馈。"""

    assert controller._current_word is None
    entry = _entry(3)
    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_detail_mastered(entry)

    assert controller._mastered.count() == 1
    assert entry.id in controller._mastered.ids()
    assert C.JP_NOTIFY_MASTERED_ADDED.format(word=entry.word, kana=entry.kana) in captured
    assert controller._daily_log.count_for(_DAY) == 0


def test_detail_mastered_duplicate_gives_duplicate_feedback(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """重复标记 → mastered 不重复入库，托盘反馈为「已经掌握啦」（与气泡按钮一致）。"""

    entry = _entry(4)
    controller._mark_word_mastered(entry, _ISO)
    assert controller._mastered.count() == 1

    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_detail_mastered(entry)

    assert controller._mastered.count() == 1
    assert C.JP_NOTIFY_MASTERED_DUPLICATE in captured
    assert C.JP_NOTIFY_MASTERED_ADDED.format(word=entry.word, kana=entry.kana) not in captured


def test_detail_mastered_none_entry_noop(controller: PetAppController) -> None:
    """空词条守卫：不落库、不抛异常。"""

    controller._on_detail_mastered(None)

    assert controller._mastered.count() == 0
    assert controller._daily_log.count_for(_DAY) == 0


# --------------------------------------------------------------------------- #
# 3. 端到端：打开详情 → 按钮初始态同步 / 点击落库并置已掌握态
# --------------------------------------------------------------------------- #
def test_open_detail_syncs_mastered_button_state(controller: PetAppController) -> None:
    """已掌握词打开详情 → 按钮初始即「已掌握」禁用态；未掌握词 → 「记住了」可点击。"""

    mastered_entry = _entry(5)
    controller._mastered.add(mastered_entry, _ISO)

    controller._open_word_detail(mastered_entry)
    btn = controller._detail_window._mastered_btn
    assert btn.text() == C.WORD_DETAIL_MASTERED_DONE
    assert not btn.isEnabled()

    controller._open_word_detail(_entry(6))
    assert btn.text() == C.JP_BUTTON_MASTERED
    assert btn.isEnabled()


def test_detail_window_click_marks_mastered_end_to_end(controller: PetAppController) -> None:
    """窗口点击「记住了」→ 复用同一逻辑落库 + 按钮转「已掌握」禁用态（视觉反馈一致）。"""

    entry = _entry(7)
    controller._open_word_detail(entry)
    btn = controller._detail_window._mastered_btn
    assert btn.isEnabled()

    btn.click()

    assert entry.id in controller._mastered.ids()
    assert controller._daily_log.count_for(_DAY) == 0
    assert btn.text() == C.WORD_DETAIL_MASTERED_DONE
    assert not btn.isEnabled()


# --------------------------------------------------------------------------- #
# 4. 颜色：与气泡按钮同源绿（success token == jp_button_primary_bg）
# --------------------------------------------------------------------------- #
def test_mastered_button_uses_success_variant_green(qtbot) -> None:
    """详情「记住了」按钮取 ``success`` 变体，且该变体色值即气泡按钮绿。"""

    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    btn = window._mastered_btn

    assert btn.property("variant") == "success"
    # 色值同源：semantic success == 气泡按钮底色（design-tokens 已钉死，此处二次守护）
    assert C.SEMANTIC_COLORS["success"] == C.COLORS["jp_button_primary_bg"]
    # 变体确实进了 QSS（不是「设了属性但无样式」的死配置）
    qss = theme.build_qss()
    assert 'QPushButton[variant="success"]' in qss
    assert C.SEMANTIC_COLORS["success"] in qss


def test_mastered_button_renders_bubble_green_pixel(qtbot) -> None:
    """离屏实渲染取色：按钮中心像素 ≈ 气泡按钮绿（抓「设了变体却没上色」）。

    渐变改版后中心像素落在 0.5 停靠点的哪一侧由按钮尺寸奇偶决定（±1/通道），
    故取 ±2/通道 容差——未上色（白底）或错色按钮差出几十以上，足以分辨。
    """

    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    window.resize(C.WORD_DETAIL_WINDOW_W, C.WORD_DETAIL_WINDOW_H)
    window.show_entry(_entry(1), WordDetail(meaning_zh=("义",)), "来源")
    window.show()
    QApplication.processEvents()

    image = window._mastered_btn.grab().toImage()
    center = image.pixelColor(image.width() // 2, image.height() // 2)
    expected = C.COLORS["jp_button_primary_bg"].upper()
    er, eg, eb = (int(expected[i : i + 2], 16) for i in (1, 3, 5))
    assert abs(center.red() - er) <= 2
    assert abs(center.green() - eg) <= 2
    assert abs(center.blue() - eb) <= 2


# --------------------------------------------------------------------------- #
# 5. 生词本同步：掌握处置必须移出生词本 + 即时刷新窗口
# --------------------------------------------------------------------------- #
def test_detail_mastered_removes_from_vocab_and_refreshes_window(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """详情「记住了」→ 该词即时从生词本移除，且窗口收到 refresh（数据与展示一致）。"""

    entry = _entry(8)
    controller._vocab.add(entry, _ISO)
    fake_window = _FakeVocabWindow()
    controller._vocab_window = fake_window  # type: ignore[assignment]
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: None)

    controller._on_detail_mastered(entry)

    assert entry.id not in {item.id for item in controller._vocab.items()}
    assert controller._vocab.count() == 0
    assert fake_window.refreshed, "生词本窗口应收到 refresh 调用"
    assert [item.id for item in fake_window.refreshed[-1]] == []
    assert entry.id in controller._mastered.ids()


def test_detail_mastered_feedback_mentions_vocab_removal(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """移出生词本时反馈文案带「已移出生词本」后缀（简短操作反馈）。"""

    entry = _entry(9)
    controller._vocab.add(entry, _ISO)
    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_detail_mastered(entry)

    expected = C.JP_NOTIFY_MASTERED_ADDED.format(word=entry.word, kana=entry.kana)
    expected += C.JP_NOTIFY_VOCAB_REMOVED_SUFFIX
    assert captured == [expected]


def test_detail_mastered_not_in_vocab_keeps_plain_feedback(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """不在生词本时：反馈文案不加后缀（避免误导）。"""

    entry = _entry(10)
    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_detail_mastered(entry)

    assert captured == [
        C.JP_NOTIFY_MASTERED_ADDED.format(word=entry.word, kana=entry.kana)
    ]


def test_detail_mastered_duplicate_still_removes_vocab_with_suffix(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """已掌握但仍在生词本（历史数据）→ 重复文案 + 移除后缀，且确实移出。"""

    entry = _entry(11)
    controller._mark_word_mastered(entry, _ISO)
    controller._vocab.add(entry, _ISO)
    captured: list[str] = []
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: captured.append(msg))

    controller._on_detail_mastered(entry)

    assert captured == [C.JP_NOTIFY_MASTERED_DUPLICATE + C.JP_NOTIFY_VOCAB_REMOVED_SUFFIX]
    assert controller._vocab.count() == 0
    assert controller._mastered.count() == 1


def test_bubble_mastered_also_removes_from_vocab(controller: PetAppController) -> None:
    """气泡按钮路径同样移出生词本（两个「记住了」行为一致，非详情独有）。"""

    controller._show_word_bubble(0.0)
    word = controller._current_word
    assert word is not None
    controller._on_word_vocab()  # 先记为生词
    assert word.id in {item.id for item in controller._vocab.items()}

    # 该词再次成为当前展示词后点气泡「记住了」
    controller._current_word = word
    controller._word_disposed = False
    controller._on_word_mastered()

    assert controller._vocab.count() == 0
    assert word.id in controller._mastered.ids()


def test_full_loop_double_click_then_mastered_clears_vocab(
    controller: PetAppController, monkeypatch: pytest.MonkeyPatch
) -> None:
    """闭环：双击气泡（记生词 + 开详情）→ 详情点「记住了」→ 生词本清空、mastered 收录。"""

    controller._show_word_bubble(0.0)
    word = controller._current_word
    assert word is not None
    monkeypatch.setattr(controller._tray, "notify", lambda title, msg: None)

    controller._on_bubble_word_detail(word)
    assert word.id in {item.id for item in controller._vocab.items()}

    controller._on_detail_mastered(word)

    assert controller._vocab.count() == 0
    assert word.id in controller._mastered.ids()
