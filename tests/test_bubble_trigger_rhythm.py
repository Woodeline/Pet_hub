"""情绪气泡触发节奏回归测试（2026-09-26 调整）。

背景与目标：
- 旧行为：键盘敲击 -> 状态机瞬时表情（FOCUS/EXCITED/SURPRISED/SULKY）-> 立即弹气泡，
  节流只有 ``BUBBLE_MIN_GAP_S``(3s)，高频打字时几乎每 3 秒糊一条 → 频率过高。
- 新行为：
  1. **自动来源**（敲击驱动 / 状态机迁移 / 休息态呵欠）统一受
     ``[BUBBLE_MIN_INTERVAL_S, BUBBLE_MAX_INTERVAL_S]``（20s ~ 60s）随机窗口节流；
  2. **鼠标来源**（悬停抚摸 / 点击）走 ``immediate=True``，保留「移上去立即显示一条」；
  3. 键盘专属文案（``KEYBOARD_BUBBLE_EXPRESSIONS``）必须含键盘关键字，
     且只由敲击路径驱动；鼠标文案（HAPPY）不得含键盘关键字。

覆盖清单：
1. 常量字面量 + ``__all__`` 登记；
2. 排期窗口落在 [20, 60]（大样本采样，且证明上界确实到 1 分钟）；
3. 自动来源被窗口节流（旧「每 3 秒一条」不再成立）；
4. ``immediate`` 绕过窗口（鼠标「立即显示」）；
5. 硬下限 ``BUBBLE_MIN_GAP_S`` 对 ``immediate`` 依然生效（防连弹）；
6. 连续高频打字 60 秒内的气泡条数 ≤ 4（频率被压低）；
7. 键盘专属键的文案（默认包 + 全部预设包）都含键盘关键字；
8. 鼠标键 HAPPY 的文案不含键盘关键字；且 HAPPY / Mood.* 不属于键盘键集；
9. 源码级隔离：手势路径只用 HAPPY + immediate。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import desktop_pet.app.controller as controller_module
from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.vocab_store import VocabStore


@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """最小 controller：store 指向 tmp_path，气泡开关打开，节流状态复位。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)

    ctrl._cfg.bubble_enabled = True

    ctrl._mastered = MasteredStore(tmp_path / "mastered.json")
    ctrl._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    ctrl._vocab = VocabStore(tmp_path / "vocab.json")
    ctrl._mastered.load()
    ctrl._daily_log.load()
    ctrl._vocab.load()

    ctrl._today_str = "2025-01-01"
    ctrl._last_bubble_ts = float("-inf")
    ctrl._next_bubble_ts = float("-inf")
    return ctrl


# --------------------------------------------------------------------------- #
# 1. 常量字面量 + __all__ 登记
# --------------------------------------------------------------------------- #
def test_interval_constants_literal_and_exported() -> None:
    assert C.BUBBLE_MIN_INTERVAL_S == 20.0
    assert C.BUBBLE_MAX_INTERVAL_S == 60.0
    for name in (
        "BUBBLE_MIN_INTERVAL_S",
        "BUBBLE_MAX_INTERVAL_S",
        "KEYBOARD_BUBBLE_EXPRESSIONS",
        "BUBBLE_KEYBOARD_KEYWORDS",
    ):
        assert name in C.__all__, f"{name} 未登记进 constants.__all__"


# --------------------------------------------------------------------------- #
# 2. 排期窗口落在 [20, 60]
# --------------------------------------------------------------------------- #
def test_next_bubble_window_sampled_within_bounds(controller: PetAppController) -> None:
    """自动展示成功后，下一次自动窗口必须落在 [20, 60] 秒且上界可达 1 分钟。"""

    deltas: list[float] = []
    for _ in range(400):
        controller._last_bubble_ts = float("-inf")
        controller._next_bubble_ts = float("-inf")
        controller._show_bubble_for(C.Mood.IDLE, 1000.0)
        deltas.append(controller._next_bubble_ts - 1000.0)

    assert all(20.0 <= d <= 60.0 for d in deltas), f"超出窗口：{min(deltas)}~{max(deltas)}"
    assert max(deltas) > 50.0, "上界未真正拓宽到 1 分钟附近"
    assert min(deltas) < 30.0, "下界未真正落在 20 秒附近"


# --------------------------------------------------------------------------- #
# 3. 自动来源被随机窗口节流
# --------------------------------------------------------------------------- #
def test_auto_source_throttled_inside_window(controller: PetAppController) -> None:
    """自动来源在窗口内（> 硬下限但 < 20s）不得再次展示。"""

    controller._show_bubble_for(C.Mood.IDLE, 0.0)
    assert controller._last_bubble_ts == 0.0
    assert controller._next_bubble_ts >= 20.0

    # 4 秒后（已过 3s 硬下限，但远未到随机窗口）→ 不展示
    controller._show_bubble_for(C.Mood.IDLE, 4.0)
    assert controller._last_bubble_ts == 0.0, "自动来源未被随机窗口节流"


def test_auto_source_shows_again_after_window(controller: PetAppController) -> None:
    controller._show_bubble_for(C.Mood.IDLE, 0.0)
    window = controller._next_bubble_ts
    controller._show_bubble_for(C.Mood.IDLE, window + 0.001)
    assert controller._last_bubble_ts == window + 0.001


# --------------------------------------------------------------------------- #
# 4~5. 鼠标 immediate 路径
# --------------------------------------------------------------------------- #
def test_immediate_bypasses_random_window(controller: PetAppController) -> None:
    """鼠标悬停/点击：窗口内也应立即展示（保留「移上去立即显示一条」）。"""

    controller._show_bubble_for(C.Expression.HAPPY, 0.0)
    assert controller._last_bubble_ts == 0.0

    # 4 秒后鼠标移上去 → 立即展示（自动来源此时会被拦）
    controller._show_bubble_for(C.Expression.HAPPY, 4.0, immediate=True)
    assert controller._last_bubble_ts == 4.0, "immediate 未绕过随机窗口"

    # 且 immediate 也重排了自动窗口，避免紧随其后再糊一条
    assert controller._next_bubble_ts >= 4.0 + 20.0


def test_immediate_still_obeys_hard_gap(controller: PetAppController) -> None:
    """硬下限对鼠标同样生效，避免反复进出连弹。"""

    controller._show_bubble_for(C.Expression.HAPPY, 0.0)
    controller._show_bubble_for(C.Expression.HAPPY, C.BUBBLE_MIN_GAP_S - 0.5, immediate=True)
    assert controller._last_bubble_ts == 0.0, "硬下限被 immediate 绕过"


# --------------------------------------------------------------------------- #
# 6. 高频打字 60 秒内的气泡条数被压低
# --------------------------------------------------------------------------- #
def test_typing_60s_bubble_count_is_low(controller: PetAppController) -> None:
    """模拟 60 秒连续高频打字：气泡条数应 ≤ 4（旧行为会是 ~20 条）。"""

    shown = 0
    t = 0.0
    for i in range(600):  # 0.1s 一次，共 60 秒
        t = i * 0.1
        controller._on_keystroke(t)
        if controller._last_bubble_ts == t:
            shown += 1

    assert shown >= 1, "至少应展示过一条（首次窗口开放）"
    assert shown <= 4, f"高频打字抑制失效：60 秒内展示了 {shown} 条"


# --------------------------------------------------------------------------- #
# 7~8. 文案与触发方式匹配
# --------------------------------------------------------------------------- #
def _all_texts_for(key) -> list[tuple[str, str]]:
    """返回某键在「默认包 + 全部预设包」中的 (来源, 文案) 列表。"""

    out: list[tuple[str, str]] = []
    for text in C.BUBBLE_TEXTS.get(key, []):
        out.append(("default", text))
    for pack_name, pack in C.BUBBLE_TEXT_PACKS.items():
        for text in pack.get(key, []):
            out.append((pack_name, text))
    return out


def test_keyboard_texts_contain_keyboard_keyword() -> None:
    """键盘专属键的**所有**文案都必须含键盘关键字（默认包 + 各预设包）。"""

    assert C.KEYBOARD_BUBBLE_EXPRESSIONS, "键盘专属键集不得为空"
    for key in C.KEYBOARD_BUBBLE_EXPRESSIONS:
        items = _all_texts_for(key)
        assert items, f"{key} 没有任何气泡文案"
        for source, text in items:
            assert any(kw in text for kw in C.BUBBLE_KEYBOARD_KEYWORDS), (
                f"[{source}] {key.name} 文案缺少键盘关键字：{text}"
            )


def test_mouse_texts_have_no_keyboard_keyword() -> None:
    """鼠标键 HAPPY 的文案不得含键盘关键字（避免「摸一下」看到键盘文案）。"""

    for source, text in _all_texts_for(C.Expression.HAPPY):
        assert not any(kw in text for kw in C.BUBBLE_KEYBOARD_KEYWORDS), (
            f"[{source}] HAPPY 文案混入了键盘关键字：{text}"
        )


def test_keyboard_set_excludes_mouse_and_auto_keys() -> None:
    """鼠标键与帧循环自动迁移用的 Mood 键都不得进入键盘专属键集。"""

    assert C.Expression.HAPPY not in C.KEYBOARD_BUBBLE_EXPRESSIONS
    for mood in (C.Mood.IDLE, C.Mood.REST, C.Mood.SLEEP):
        assert mood not in C.KEYBOARD_BUBBLE_EXPRESSIONS, f"{mood} 不应属于键盘专属键"


# --------------------------------------------------------------------------- #
# 9. 源码级隔离：手势路径只用 HAPPY + immediate
# --------------------------------------------------------------------------- #
def test_gesture_path_uses_happy_and_immediate_only() -> None:
    src = Path(controller_module.__file__).read_text(encoding="utf-8")
    segment = src.split("def _on_gesture")[1].split("def _on_position_changed")[0]

    assert "immediate=True" in segment, "鼠标手势路径未走 immediate"
    for forbidden in ("Expression.FOCUS", "Expression.EXCITED", "Expression.SULKY", "Expression.SURPRISED"):
        assert forbidden not in segment, f"鼠标手势路径混入了键盘专属表情 {forbidden}"


def test_keystroke_path_uses_shared_keyboard_keyset() -> None:
    """敲击路径必须引用 constants 里的唯一来源，不得各自复制一份键集。"""

    src = Path(controller_module.__file__).read_text(encoding="utf-8")
    segment = src.split("def _on_keystroke")[1].split("def _on_frame_tick")[0]

    assert "C.KEYBOARD_BUBBLE_EXPRESSIONS" in segment
    assert "_BUBBLE_EXPRESSIONS = " not in src, "私有重复键集应已删除，改为引用 constants 唯一来源"
