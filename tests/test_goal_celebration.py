"""工程师自测：每日目标庆祝 —— 新词 / 复习达标一次性庆祝（EXCITED + 祝贺气泡）。

覆盖：
1. PetModel.celebrate：EXCITED 临时表情 + 默认时长（常量），到期回落由既有机制承担。
2. 复习达标：_maybe_notify_review_done 首次触发庆祝且置一次性标志，重复调用不重复。
3. 新词达标：_show_word_bubble 停止分支首次触发庆祝（不弹词）。
4. 气泡开关关闭：庆祝仍给猫表情，但不弹气泡（装饰性反馈不破坏既有通知语义）。

遵循项目测试隔离约定（配置 / 数据落 tmp_path，墙钟注入替身）。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.constants import Expression
from desktop_pet.core.daily_log_store import DailyLogEntry, DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.pet_model import PetModel
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker

_DAY: str = "2025-01-01"
_ISO: str = "2025-01-01T00:00:00Z"


def _log_entry(word_id: int, status: str) -> DailyLogEntry:
    return DailyLogEntry(
        id=f"n5-{word_id:04d}",
        level="N5",
        word=f"語{word_id}",
        kana="かな",
        translation="译",
        shown_at=f"{_DAY}T00:00:00Z",
        status=status,
    )


@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """构造最小 controller（同 test_review_scheduler 范式）。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.jp_enabled = True
    ctrl._cfg.bubble_enabled = True
    ctrl._cfg.jp_level = "N5"
    ctrl._cfg.jp_daily_limit = 5
    ctrl._cfg.jp_review_daily_limit = 3
    ctrl._cfg.jp_bubble_duration_s = 30

    ctrl._bank = WordBank.empty()
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


# --------------------------------------------------------------------------- #
# PetModel.celebrate
# --------------------------------------------------------------------------- #
def test_celebrate_sets_excited_with_default_duration() -> None:
    """celebrate() → EXCITED 临时表情，时长为常量默认值。"""

    model = PetModel()
    model.celebrate()
    assert model._temp_expression == Expression.EXCITED
    assert model._temp_remaining == pytest.approx(C.CELEBRATION_DURATION_S)


def test_celebrate_custom_duration() -> None:
    """显式时长覆盖默认值。"""

    model = PetModel()
    model.celebrate(1.5)
    assert model._temp_expression == Expression.EXCITED
    assert model._temp_remaining == pytest.approx(1.5)


# --------------------------------------------------------------------------- #
# 复习达标庆祝
# --------------------------------------------------------------------------- #
def test_review_quota_reached_celebrates_once(controller: PetAppController) -> None:
    """复习作答达标：首次通知 + 庆祝（EXCITED），重复调用不重复庆祝。"""

    for i in range(controller._cfg.jp_review_daily_limit):
        controller._daily_log.add_entry(_DAY, _log_entry(i, "review_ok"))

    controller._maybe_notify_review_done()
    assert controller._review_done_notified is True
    assert controller._model._temp_expression == Expression.EXCITED

    # 一次性标志：再次调用直接返回（不重复庆祝、不重置表情时长以外副作用）
    controller._maybe_notify_review_done()
    assert controller._review_done_notified is True


def test_review_celebration_skips_bubble_when_disabled(
    controller: PetAppController,
) -> None:
    """气泡开关关闭：猫照样开心（EXCITED），但不弹祝贺气泡。"""

    controller._cfg.bubble_enabled = False
    for i in range(controller._cfg.jp_review_daily_limit):
        controller._daily_log.add_entry(_DAY, _log_entry(i, "review_ok"))

    controller._maybe_notify_review_done()
    assert controller._model._temp_expression == Expression.EXCITED
    assert controller._bubble.isVisible() is False


# --------------------------------------------------------------------------- #
# 新词达标庆祝
# --------------------------------------------------------------------------- #
def test_new_word_quota_reached_celebrates(controller: PetAppController) -> None:
    """新词达标：_show_word_bubble 停止分支首次触发庆祝且不展示单词。"""

    for i in range(controller._cfg.jp_daily_limit):
        controller._daily_log.add_entry(_DAY, _log_entry(i, "vocab"))

    controller._show_word_bubble(0.0)
    assert controller._current_word is None  # 未弹词（配额已满）
    assert controller._today_done_notified is True
    assert controller._model._temp_expression == Expression.EXCITED

    # 一次性：第二次到点不再庆祝（标志已置位）
    controller._model.set_expression(Expression.HAPPY, 0.1)
    controller._show_word_bubble(100.0)
    assert controller._model._temp_expression == Expression.HAPPY
