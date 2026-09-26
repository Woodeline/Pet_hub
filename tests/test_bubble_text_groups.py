"""情绪气泡台词分组与键盘关键字门控回归测试（2026-09-26 需求 C）。

用户需求（四项）：
1. **关键字触发**：自定义文案含「键盘」等键盘关键字时，该条不得被自动触发，
   仅在检测到键盘敲击事件时才允许触发；
2. **频率控制**：自动触发间隔在 20 秒 ~ 1 分钟之间随机取值（由需求 B 落地，
   本文件做交叉校验，主守护在 tests/test_bubble_trigger_rhythm.py）；
3. **保留行为**：鼠标移到宠物上仍立即显示一条，且该条不含键盘关键字；
4. **文案分组**：自定义台词分「自动触发组」与「敲击键盘组」两组，触发来源与
   显示规则明确（UI 见 test_bubble_text_dialog.py）。

本文件守护 1 / 3 / 4 的行为契约 + 源码级触发源隔离。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

import desktop_pet.app.controller as controller_module
from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.constants import Expression, Mood

#: 自动侧（非敲击路径）实际会用到的键：帧循环迁移 + 休息态呵欠 + 鼠标手势
AUTO_SIDE_KEYS = (Expression.HAPPY, Expression.YAWN, Mood.IDLE, Mood.REST, Mood.SLEEP)


@pytest.fixture()
def controller(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """最小 controller：气泡开关打开，节流状态复位。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    ctrl = PetAppController(qapp, store)
    ctrl._cfg.bubble_enabled = True
    ctrl._last_bubble_ts = float("-inf")
    ctrl._next_bubble_ts = float("-inf")
    ctrl._next_kb_bubble_ts = float("-inf")
    return ctrl


@pytest.fixture()
def shown(controller: PetAppController, monkeypatch) -> list[str]:
    """拦截实际展示的文案（记录 BubbleWindow.show_message 的实参）。"""

    captured: list[str] = []
    monkeypatch.setattr(controller._bubble, "show_message", lambda text, duration: captured.append(text))
    return captured


def _all_texts_of(controller: PetAppController, key, *, keyboard: bool = False) -> set[str]:
    """某键在该触发源下的完整可选文案集合（不受节流影响）。"""

    return set(controller._bubble_texts_for(key, keyboard=keyboard) or [])


# --------------------------------------------------------------------------- #
# 0. 常量层：关键字判定工具是唯一事实源
# --------------------------------------------------------------------------- #
def test_keyword_helpers_exported_and_literal() -> None:
    for name in ("has_keyboard_keyword", "filter_keyboard_texts"):
        assert name in C.__all__, f"{name} 未登记进 constants.__all__"

    assert C.has_keyboard_keyword("键盘敲得真快！") is True
    assert C.has_keyboard_keyword("摸摸我呀~") is False
    assert C.filter_keyboard_texts(["摸摸我呀~", "键盘敲得真快！", "加油鸭！"]) == [
        "摸摸我呀~",
        "加油鸭！",
    ]


def test_filter_uses_shared_keyword_tuple() -> None:
    """过滤依据必须来自 BUBBLE_KEYBOARD_KEYWORDS（词表每一项都要命中）。"""

    assert C.BUBBLE_KEYBOARD_KEYWORDS == ("键盘", "敲", "打字", "码字", "手速", "按键")
    for kw in C.BUBBLE_KEYBOARD_KEYWORDS:
        assert C.has_keyboard_keyword(f"前缀{kw}后缀") is True
    # 词表之外的字样不得被误判
    assert C.has_keyboard_keyword("鼠标点了一下") is False
    assert C.has_keyboard_keyword(C.BUBBLE_TEXTS[Mood.IDLE][0]) is False


# --------------------------------------------------------------------------- #
# 1. 关键字门控：自动侧永不出含键盘关键字的文案
# --------------------------------------------------------------------------- #
def test_auto_pool_filters_keyboard_lines(controller: PetAppController) -> None:
    """需求 C-1：自动组里含键盘关键字的行被静默过滤，其余照常生效。"""

    controller._cfg.bubble_texts_custom = ["摸摸我呀~", "键盘敲得真快！", "加油鸭！"]

    assert controller._bubble_texts_for(Mood.IDLE) == ["摸摸我呀~", "加油鸭！"]


def test_auto_pool_all_keyboard_falls_back_to_pack(controller: PetAppController) -> None:
    """需求 C-1：自动组全被过滤时视为「未配置」→ 回落预设包，而非静默不弹。"""

    controller._cfg.bubble_texts_custom = ["键盘敲得真快！", "手速太快啦！"]
    controller._cfg.bubble_text_pack = "default"

    texts = controller._bubble_texts_for(Mood.IDLE)
    assert texts == C.BUBBLE_TEXTS[Mood.IDLE]
    assert not any(C.has_keyboard_keyword(t) for t in texts)


def test_auto_side_never_returns_keyboard_text(controller: PetAppController, shown: list[str]) -> None:
    """端到端：自动侧任意键、任意预设包组合下，展示文案都不含键盘关键字。"""

    controller._cfg.bubble_texts_custom = ["键盘敲得真快！", "普通台词"]
    controller._cfg.bubble_texts_custom_keyboard = ["敲击专属台词"]

    for pack in C.BUBBLE_TEXT_PACK_ALLOWED:
        controller._cfg.bubble_text_pack = pack
        for key in AUTO_SIDE_KEYS + tuple(C.KEYBOARD_BUBBLE_EXPRESSIONS):
            controller._last_bubble_ts = float("-inf")
            controller._next_bubble_ts = float("-inf")
            controller._show_bubble_for(key, 1000.0)
            controller._last_bubble_ts = float("-inf")
            controller._next_bubble_ts = float("-inf")
            controller._show_bubble_for(key, 1000.0, immediate=True)

    offenders = [t for t in shown if C.has_keyboard_keyword(t)]
    assert not offenders, f"自动侧展示了含键盘关键字的文案：{offenders}"


def test_auto_side_core_keys_are_never_empty(controller: PetAppController) -> None:
    """自动侧的核心键（正常情绪/呵欠/鼠标）在任何预设包下都不会被过滤到空。

    否则用户什么都没配也会看不到自动气泡 —— 这是「过滤把池掏空」的回归哨兵。
    """

    controller._cfg.bubble_texts_custom = []
    controller._cfg.bubble_texts_custom_keyboard = []
    for pack in C.BUBBLE_TEXT_PACK_ALLOWED:
        controller._cfg.bubble_text_pack = pack
        for key in AUTO_SIDE_KEYS:
            assert controller._bubble_texts_for(key), f"包 {pack} 的 {key} 自动侧被过滤空"


def test_auto_fallback_path_also_filters_keyboard_text(controller: PetAppController) -> None:
    """过滤必须覆盖「回落预设台词包 / 内置文案表」这一级，而不只是在自定义池上生效。

    变异验证发现：若只保留自定义池的过滤，其余断言全部照样通过 —— 因为那些用例
    的自动组非空、会自动分支提前返回，永远走不到回落路径。此用例专门用**自动组为空**
    触发回落，把这一级也钉死。

    内置表中键盘专属键（``KEYBOARD_BUBBLE_EXPRESSIONS``）的文案全部含键盘关键字，
    故自动侧取用后被过滤一空 → 返回 ``None``（调用方放弃展示）；而敲击侧必须照常取到。
    """

    controller._cfg.bubble_texts_custom = []
    controller._cfg.bubble_texts_custom_keyboard = []
    controller._cfg.bubble_text_pack = "default"

    assert C.KEYBOARD_BUBBLE_EXPRESSIONS, "键盘专属键集不得为空"
    for key in C.KEYBOARD_BUBBLE_EXPRESSIONS:
        assert controller._bubble_texts_for(key) is None, (
            f"{key.name} 从自动侧回落路径漏出了键盘文案"
        )
        assert controller._bubble_texts_for(key, keyboard=True) == C.BUBBLE_TEXTS[key]


def test_auto_fallback_path_filters_pack_texts(
    controller: PetAppController, monkeypatch
) -> None:
    """预设台词包同样受过滤：给 energy 包中自动侧键注入键盘词后必须被剔除。"""

    controller._cfg.bubble_texts_custom = []
    controller._cfg.bubble_texts_custom_keyboard = []
    controller._cfg.bubble_text_pack = "energy"

    # 用 monkeypatch 改写包内容（测试结束自动还原，避免污染全局常量）
    pack = dict(C.BUBBLE_TEXT_PACKS["energy"])
    pack[Mood.IDLE] = ["键盘陪你冲！", "我在呢~"]
    monkeypatch.setitem(C.BUBBLE_TEXT_PACKS, "energy", pack)

    assert controller._bubble_texts_for(Mood.IDLE) == ["我在呢~"]


# --------------------------------------------------------------------------- #
# 3. 鼠标路径：立即显示且不含键盘关键字
# --------------------------------------------------------------------------- #
def test_mouse_immediate_bypasses_window_and_has_no_keyboard_text(
    controller: PetAppController, shown: list[str]
) -> None:
    """需求 C-3：鼠标移上去立即显示（绕过窗口），且文案不含键盘关键字。"""

    controller._cfg.bubble_texts_custom = ["摸摸我呀~", "键盘敲得真快！"]
    controller._cfg.bubble_texts_custom_keyboard = ["敲击专属台词"]

    controller._show_bubble_for(Expression.HAPPY, 0.0)
    assert controller._last_bubble_ts == 0.0

    # 4 秒后（自动侧仍被窗口拦截）鼠标移入 → 立即展示
    controller._show_bubble_for(Expression.HAPPY, 4.0, immediate=True)
    assert controller._last_bubble_ts == 4.0, "鼠标路径未立即展示"
    assert not any(C.has_keyboard_keyword(t) for t in shown), f"鼠标路径出现键盘文案：{shown}"


def test_mouse_path_does_not_use_keyboard_pool(controller: PetAppController) -> None:
    """敲击组只归敲击路径：鼠标路径即使敲击组非空也看不到它。"""

    controller._cfg.bubble_texts_custom = []
    controller._cfg.bubble_texts_custom_keyboard = ["敲击专属台词"]

    assert controller._bubble_texts_for(Expression.HAPPY) != ["敲击专属台词"]


# --------------------------------------------------------------------------- #
# 4. 分组：两组互不干扰，各自独立回落
# --------------------------------------------------------------------------- #
def test_two_pools_are_independent(controller: PetAppController) -> None:
    """两组各自独立：敲击组非空不影响自动组，反之亦然。"""

    controller._cfg.bubble_texts_custom = ["自动专属"]
    controller._cfg.bubble_texts_custom_keyboard = ["敲击专属"]

    assert controller._bubble_texts_for(Mood.IDLE) == ["自动专属"]
    assert controller._bubble_texts_for(Expression.FOCUS, keyboard=True) == ["敲击专属"]


def test_keyboard_pool_keeps_keyboard_lines(controller: PetAppController) -> None:
    """需求 C-1 反面：敲击组**不**做关键字过滤 —— 敲击时就该看到键盘文案。"""

    controller._cfg.bubble_texts_custom_keyboard = ["键盘冒火星啦！", "普通敲击台词"]

    assert controller._bubble_texts_for(Expression.FOCUS, keyboard=True) == [
        "键盘冒火星啦！",
        "普通敲击台词",
    ]


def test_keyboard_side_falls_back_to_pack_when_pool_empty(controller: PetAppController) -> None:
    """敲击组为空 → 回落预设包（键盘专属键的预设文案含键盘关键字，符合直觉）。"""

    controller._cfg.bubble_texts_custom_keyboard = []
    controller._cfg.bubble_text_pack = "default"

    texts = controller._bubble_texts_for(Expression.FOCUS, keyboard=True)
    assert texts == C.BUBBLE_TEXTS[Expression.FOCUS]
    assert all(C.has_keyboard_keyword(t) for t in texts)


# --------------------------------------------------------------------------- #
# 5. 频率：自动侧 20~60s 窗口（交叉校验，主守护在 test_bubble_trigger_rhythm.py）
# --------------------------------------------------------------------------- #
def test_auto_window_still_20_to_60(controller: PetAppController) -> None:
    deltas: list[float] = []
    for _ in range(300):
        controller._last_bubble_ts = float("-inf")
        controller._next_bubble_ts = float("-inf")
        controller._show_bubble_for(Mood.IDLE, 1000.0)
        deltas.append(controller._next_bubble_ts - 1000.0)

    assert all(C.BUBBLE_MIN_INTERVAL_S <= d <= C.BUBBLE_MAX_INTERVAL_S for d in deltas)
    assert C.BUBBLE_MIN_INTERVAL_S == 20.0
    assert C.BUBBLE_MAX_INTERVAL_S == 60.0


# --------------------------------------------------------------------------- #
# 6. 源码级触发源隔离
# --------------------------------------------------------------------------- #
def _segment(name: str, end: str) -> str:
    src = Path(controller_module.__file__).read_text(encoding="utf-8")
    return src.split(f"def {name}")[1].split(f"def {end}")[0]


def test_keystroke_path_marks_keyboard_source() -> None:
    """敲击路径必须显式声明 keyboard=True（否则敲击文案会被自动侧过滤掉）。

    2026-09-26 重做后：三个分支（键盘专属表情 / 情绪态迁移 / 稳态敲击回落 FOCUS）
    先选 key，再统一以 ``keyboard=True`` 调用一次 —— 稳态敲击（无迁移）也走敲击组，
    保证「敲了键盘就能按节奏看到敲击组文案」。
    """

    segment = _segment("_on_keystroke", "_on_frame_tick")
    assert "C.KEYBOARD_BUBBLE_EXPRESSIONS" in segment, "键盘专属键集未引用 constants 唯一来源"
    assert "key = transition.expression" in segment, "键盘专属表情分支未选 key"
    assert "key = transition.to_mood" in segment, "情绪态迁移分支未选 key"
    assert "key = Expression.FOCUS" in segment, "稳态敲击缺少 FOCUS 回落（敲了却看不到敲击组文案）"
    assert (
        "self._show_bubble_for(key, now, keyboard=True)" in segment
    ), "敲击路径未以 keyboard=True 统一调用"


def test_frame_and_gesture_paths_do_not_mark_keyboard() -> None:
    """帧循环与鼠标手势路径都不得标记 keyboard=True（必须走自动侧过滤）。"""

    frame = _segment("_on_frame_tick", "_on_gesture")
    gesture = _segment("_on_gesture", "_on_position_changed")
    assert "keyboard=True" not in frame, "帧循环路径不应标记键盘来源"
    assert "keyboard=True" not in gesture, "鼠标手势路径不应标记键盘来源"
    assert "immediate=True" in gesture


# --------------------------------------------------------------------------- #
# 7. 2026-09-26 重做：自动排期器（递归定时器）+ 独立敲击窗 + 稳态敲击触发
#    （旧行为缺陷：20~60s 只是事件节流阀——安静待机永远不说话、稳态打字看不到敲击组）
# --------------------------------------------------------------------------- #
def test_show_bubble_returns_whether_shown(controller: PetAppController) -> None:
    """``_show_bubble_for`` 返回是否真的展示了（排期器据此决定是否保持重试语义）。"""

    controller._next_bubble_ts = 1000.0
    assert controller._show_bubble_for(Mood.IDLE, 1000.0) is True
    # 展示成功 → 自动窗重排到 20~60s 后，窗口内再次调用被拦
    assert controller._show_bubble_for(Mood.IDLE, 1001.0) is False
    # immediate 跳过窗口但仍受 3s 硬下限
    assert controller._show_bubble_for(Mood.IDLE, 1001.0, immediate=True) is False
    assert controller._show_bubble_for(Mood.IDLE, 1004.0, immediate=True) is True


def test_idle_scheduler_proactively_shows_bubble(controller: PetAppController, shown: list[str]) -> None:
    """需求 C-2 重做：安静待机（无任何事件）时，帧循环到点必须**主动**展示一条。

    旧实现只在状态迁移/呵欠/鼠标/敲击事件里顺带展示——宠物安静待着时永远不说话。
    """

    controller._next_bubble_ts = 1000.0
    controller._on_frame_tick(1000.0)
    assert shown, "自动排期器到点未主动展示（安静待机时宠物永远不说话）"
    assert all(not C.has_keyboard_keyword(t) for t in shown), "自动排期漏出键盘文案"
    assert controller._next_bubble_ts > 1000.0, "展示后未重排下一次自动窗口（非递归排期）"


def test_idle_scheduler_retries_when_blocked(controller: PetAppController, shown: list[str]) -> None:
    """到点但被守卫拦下（如单词泡泡正在展示）→ 窗口不推进，解除后下一帧补上。"""

    controller._next_bubble_ts = 1000.0
    controller._current_word = object()  # 模拟单词泡泡展示中（情绪气泡被抑制）
    controller._on_frame_tick(1000.0)
    assert shown == []
    assert controller._next_bubble_ts == 1000.0, "被抑制时窗口不应推进（否则错过整个周期）"

    controller._current_word = None  # 解除 → 下一帧补上
    controller._on_frame_tick(1000.0)
    assert shown, "抑制解除后未补上本周期展示"


def test_scheduler_skips_sleep_but_advances_window(controller: PetAppController, shown: list[str]) -> None:
    """睡觉态到点不闲聊（不打扰睡眠），但窗口照常推进（防醒来瞬间连弹）。"""

    controller._sm._state = Mood.SLEEP
    controller._next_bubble_ts = 1000.0
    controller._on_frame_tick(1000.0)
    assert shown == [], "睡觉态不应主动闲聊"
    assert controller._next_bubble_ts > 1000.0, "睡觉态窗口未推进（醒来会被立即糊一条）"


def test_steady_keystroke_triggers_keyboard_pool(controller: PetAppController, shown: list[str]) -> None:
    """需求 C-1 正向面：稳态敲击（无情绪迁移）也必须触发敲击组文案。

    旧行为只在状态迁移时才有机会弹——稳态打字时敲击组几乎永远看不到。
    """

    controller._cfg.bubble_texts_custom_keyboard = ["敲得键盘冒烟啦~~"]
    controller._cfg.bubble_texts_custom = ["只给自动组看"]

    controller._on_keystroke(1000.0)
    assert shown == ["敲得键盘冒烟啦~~"], f"稳态敲击未触发敲击组：{shown}"
    assert controller._next_kb_bubble_ts > 1000.0, "敲击展示后未重排敲击窗"
    assert controller._next_bubble_ts == float("-inf"), "敲击展示不应挪动自动窗（两组节奏独立）"


def test_keyboard_window_independent_of_auto_window(controller: PetAppController, shown: list[str]) -> None:
    """敲击窗与自动窗相互独立：自动窗关闭时敲击仍可展示，反之亦然。"""

    # 自动组刚展示 → 自动窗关闭（20~60s 后才开放）
    controller._cfg.bubble_texts_custom = ["自动组台词"]
    controller._cfg.bubble_texts_custom_keyboard = ["敲击专属台词"]
    assert controller._show_bubble_for(Mood.IDLE, 1000.0) is True
    assert controller._next_bubble_ts >= 1020.0

    # 3 秒硬下限过后敲击 → 不受自动窗影响，仍立即展示敲击组
    controller._on_keystroke(1003.5)
    assert shown[-1] == "敲击专属台词", "敲击被自动窗误拦（两窗未独立）"

    # 反向：敲击窗刚展示不影响自动窗既定排期，窗口一开就能展示自动组
    auto_next = controller._next_bubble_ts
    controller._last_bubble_ts = float("-inf")  # 越过硬下限，只考察窗口独立性
    assert controller._show_bubble_for(Mood.IDLE, auto_next + 0.01) is True
    assert shown[-1] == "自动组台词"


def test_keyboard_window_reschedules_20_to_60(controller: PetAppController) -> None:
    """敲击窗与自动窗同规格：重排值落在 [20, 60] 秒随机。"""

    for _ in range(200):
        controller._last_bubble_ts = float("-inf")
        controller._next_kb_bubble_ts = float("-inf")
        assert controller._show_bubble_for(Expression.FOCUS, 1000.0, keyboard=True) is True
        d = controller._next_kb_bubble_ts - 1000.0
        assert C.BUBBLE_MIN_INTERVAL_S <= d <= C.BUBBLE_MAX_INTERVAL_S, f"敲击窗越界：{d}"
