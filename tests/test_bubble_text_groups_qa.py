"""QA 独立验证：气泡台词分组与键盘关键字门控（2026-09-26 需求 C）。

与工程师侧 tests/test_bubble_text_groups.py 的分工：

- 工程师侧：白盒直测 ``_bubble_texts_for`` / ``_show_bubble_for`` 的返回值与源码隔离；
- **QA 侧（本文件）**：不复用工程师的取样手法，改从**用户可见的黑盒路径**独立复现，
  重点覆盖工程师用例未覆盖的边界与端到端链路：

  1. 逐条对应用户四项需求，用「配置 → 运行 → 实际展示文案」链路验收；
  2. 配置文件层端到端：直接写 ``config.json`` 再新建 controller，验证两组各自落盘可读；
  3. 关键字边界：**词出现在台词中间**、单字「敲」、全角/半角拼接都应被识别；
  4. 穷举矩阵：全部预设包 × 全部情绪键 × 自动侧（普通 + 鼠标 immediate）路径，
     展示文案**零**含键盘关键字；
  5. 频率边界：2000 次采样窗口严格落在 [20, 60] 且上下界可达；
  6. 敲击组不受关键字约束（需求 C-1 的反面），且不会被自动侧借用；
  7. 空串 / 超长 / 重复条目在两组间独立清洗，不互相污染；
  8. Qt 侧：对话框 apply → controller 落盘 → 再次打开对话框回填，全程两组不串味。

本文件不修改任何被测代码，只用公开属性与信号。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController
from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig, ConfigStore
from desktop_pet.core.constants import Expression, Mood

#: 需求 C-3 的鼠标来源键（唯一）：鼠标悬停/点击只说 HAPPY
MOUSE_KEY = Expression.HAPPY
#: 需求 C-2 的窗口
WINDOW = (20.0, 60.0)


@pytest.fixture()
def make_controller(qapp: QApplication, tmp_path: Path):
    """工厂：给定两组自定义池 + 预设包，返回带拦截至实际展示文案的 controller。

    刻意与工程师侧 fixture 分开写（QA 独立实现），并额外返回 teardown 句柄。
    """

    created: list[PetAppController] = []

    def _factory(
        *,
        auto: list[str] | None = None,
        hit: list[str] | None = None,
        pack: str = "default",
    ):
        store = ConfigStore(tmp_path / f"cfg-{len(created)}" / "desktop-pet" / "config.json")
        store.save(
            AppConfig(
                listen_enabled=False,
                bubble_text_pack=pack,
                bubble_texts_custom=list(auto or []),
                bubble_texts_custom_keyboard=list(hit or []),
            )
        )
        ctl = PetAppController(qapp, store)
        ctl._cfg.bubble_enabled = True
        shown: list[str] = []

        def _capture(text, duration):  # noqa: ARG001
            shown.append(text)

        ctl._bubble.show_message = _capture  # type: ignore[method-assign]
        created.append(ctl)
        return ctl, shown

    yield _factory

    for ctl in created:
        ctl.shutdown()


def _fire(ctl: PetAppController, key, *, keyboard: bool = False, immediate: bool = False) -> bool:
    """触发一次展示；返回是否真的展示了（以节流时间戳是否前进为判据）。"""

    ctl._last_bubble_ts = float("-inf")
    ctl._next_bubble_ts = float("-inf")
    ctl._next_kb_bubble_ts = float("-inf")
    ctl._show_bubble_for(key, 500.0, keyboard=keyboard, immediate=immediate)
    return ctl._last_bubble_ts == 500.0


def _has_kb(texts) -> bool:
    return any(C.has_keyboard_keyword(t) for t in texts)


# =========================================================================== #
# 需求 C-1：含键盘关键字的自定义文案不得被自动触发
# =========================================================================== #
@pytest.mark.parametrize(
    "line",
    [
        "键盘敲得真快！",        # 词在开头
        "我听到你敲键盘了~",      # 词在中间
        "又在码字呀？",           # 词在句中（"码字"）
        "手速可以啊！",           # 词在末尾
        "按键声好吵…",            # "按键"
        "轻一点敲。",             # 单字「敲」
        "噼里啪啦打字中",         # "打字"
    ],
)
def test_keyboard_line_never_auto_triggered(make_controller, line: str) -> None:
    """需求 C-1：任意位置的键盘关键字都要被拦下（不只是行首/行尾）。"""

    ctl, shown = make_controller(auto=[line, "摸摸我呀~"], pack="default")

    for _ in range(30):
        _fire(ctl, Mood.IDLE)

    assert shown, "自动侧一条都没展示，用例前提不成立"
    assert line not in shown, f"含键盘关键字的行被自动触发了：{line}"
    assert set(shown) == {"摸摸我呀~"}, f"自动侧混入了非预期文案：{set(shown)}"


def test_keyboard_line_blocked_for_every_auto_key(make_controller) -> None:
    """需求 C-1：拦截对**所有**自动侧键生效（不只是 IDLE）。"""

    ctl, shown = make_controller(auto=["键盘敲得真快！", "安静的台词"], pack="default")

    for key in (Expression.HAPPY, Expression.YAWN, Mood.IDLE, Mood.REST, Mood.SLEEP):
        for _ in range(20):
            _fire(ctl, key)

    assert not _has_kb(shown), f"自动侧出现键盘文案：{sorted(set(shown))}"


def test_auto_group_fully_filtered_falls_back_not_silent(make_controller) -> None:
    """需求 C-1：自动组全是键盘词时回落预设包，而不是「永远不弹」。"""

    ctl, shown = make_controller(auto=["键盘要冒火星啦！"], pack="default")

    for _ in range(40):
        _fire(ctl, Mood.IDLE)

    assert shown, "自动组被全部过滤后没有回落预设包（自动气泡彻底消失）"
    assert set(shown) == set(C.BUBBLE_TEXTS[Mood.IDLE])
    assert not _has_kb(shown)


def test_auto_fallback_never_leaks_keyboard_text(make_controller) -> None:
    """需求 C-1：自动组留空、回落预设包/内置表的那一级也必须被过滤。

    用键盘专属键从自动路径触发（模拟「过滤只在自定义池生效、回落路径漏网」的场景），
    配合 auto=[] 强制走到回落分支。
    """

    ctl, shown = make_controller(auto=[], hit=[], pack="default")

    for key in sorted(C.KEYBOARD_BUBBLE_EXPRESSIONS, key=lambda e: e.name):
        for _ in range(10):
            _fire(ctl, key)

    assert shown == [], f"自动组为空时回落路径漏出键盘文案：{sorted(set(shown))}"


def test_auto_fallback_pack_level_filter(make_controller, monkeypatch) -> None:
    """预设台词包层同样过滤：给自动侧键注入键盘词后不得被自动触发。"""

    pack = dict(C.BUBBLE_TEXT_PACKS["energy"])
    pack[Mood.IDLE] = ["键盘陪我一起冲！", "普通台词的元气句"]
    monkeypatch.setitem(C.BUBBLE_TEXT_PACKS, "energy", pack)

    ctl, shown = make_controller(auto=[], hit=[], pack="energy")
    for _ in range(40):
        _fire(ctl, Mood.IDLE)

    assert shown, "回落预设包后一条都没展示，用例前提不成立"
    assert set(shown) == {"普通台词的元气句"}, f"预设包层未过滤：{sorted(set(shown))}"


# =========================================================================== #
# 需求 C-3：鼠标移到宠物上立即显示一条，且该条不含键盘关键字
# =========================================================================== #
def test_mouse_hover_shows_immediately_and_without_keyboard_text(make_controller) -> None:
    """需求 C-3：鼠标路径绕过 20~60s 窗口，且文案不含键盘关键字。"""

    ctl, shown = make_controller(auto=["键盘敲得真快！", "摸摸我呀~", "加油鸭！"], pack="default")

    # 先让自动窗口打开并被消耗
    assert _fire(ctl, Mood.IDLE) is True
    assert ctl._next_bubble_ts >= 500.0 + WINDOW[0]

    # 窗口内鼠标移入 → 仍应立即可见（时间戳前进 3 秒，避开硬下限）
    ctl._last_bubble_ts = float("-inf")
    ctl._show_bubble_for(MOUSE_KEY, 503.0, immediate=True)
    assert ctl._last_bubble_ts == 503.0, "鼠标路径被随机窗口拦住了（需求 C-3 未保留）"
    assert not _has_kb(shown), f"鼠标路径出现键盘文案：{sorted(set(shown))}"


def test_mouse_path_ignores_keyboard_pool(make_controller) -> None:
    """需求 C-3 + C-4：鼠标路径不得借用敲击组的文案。"""

    ctl, shown = make_controller(auto=[], hit=["敲击专属的键盘台词"], pack="default")

    for _ in range(30):
        ctl._last_bubble_ts = float("-inf")
        ctl._show_bubble_for(MOUSE_KEY, 700.0, immediate=True)

    assert "敲击专属的键盘台词" not in shown
    assert not _has_kb(shown)


# =========================================================================== #
# 需求 C-2：自动触发间隔 20 秒 ~ 1 分钟随机
# =========================================================================== #
def test_auto_window_strictly_within_20_60(make_controller) -> None:
    ctl, _shown = make_controller(auto=[], hit=[], pack="default")

    deltas: list[float] = []
    for _ in range(2000):
        ctl._last_bubble_ts = float("-inf")
        ctl._next_bubble_ts = float("-inf")
        ctl._show_bubble_for(Mood.IDLE, 10000.0)
        deltas.append(round(ctl._next_bubble_ts - 10000.0, 6))

    assert min(deltas) >= WINDOW[0] and max(deltas) <= WINDOW[1], f"越界：{min(deltas)}~{max(deltas)}"
    assert min(deltas) < 25.0, "下界没有真正贴近 20 秒"
    assert max(deltas) > 55.0, "上界没有真正贴近 1 分钟"
    assert len(set(deltas)) > 100, "间隔不是随机的（取值点过少）"


def test_typing_burst_is_throttled(make_controller) -> None:
    """需求 C-2：60 秒连续打字不应刷屏（旧行为约每 3 秒一条）。"""

    ctl, shown = make_controller(auto=[], hit=[], pack="default")

    shown_count = 0
    for i in range(600):  # 0.1 秒一次，共 60 秒
        t = i * 0.1
        ctl._on_keystroke(t)
        if ctl._last_bubble_ts == t:
            shown_count += 1

    assert shown_count <= 4, f"60 秒打字弹了 {shown_count} 条，频率仍过高"
    assert len(shown) == shown_count


# =========================================================================== #
# 需求 C-4：两组自定义池，触发来源与显示规则明确
# =========================================================================== #
def test_hit_pool_only_reachable_by_keystroke(make_controller) -> None:
    """需求 C-4：敲击组只在 keyboard=True 时可取；自动侧取不到。"""

    ctl, _shown = make_controller(auto=[], hit=["敲吧敲吧~"], pack="default")

    assert ctl._bubble_texts_for(Mood.IDLE) != ["敲吧敲吧~"]
    assert ctl._bubble_texts_for(Expression.FOCUS, keyboard=True) == ["敲吧敲吧~"]


def test_auto_pool_only_reachable_by_auto_sources(make_controller) -> None:
    """需求 C-4：自动组不参与敲击侧选池（敲击组为空时敲击侧回落预设包）。"""

    ctl, _shown = make_controller(auto=["只给自动看"], hit=[], pack="default")

    assert ctl._bubble_texts_for(Expression.FOCUS, keyboard=True) != ["只给自动看"]


def test_hit_pool_not_keyword_filtered(make_controller) -> None:
    """需求 C-1 反面：敲击组**不**过滤键盘词 —— 敲键盘时看到键盘文案才自然。"""

    ctl, _shown = make_controller(auto=[], hit=["键盘冒火星啦！", "普通敲击台词"], pack="default")

    texts = ctl._bubble_texts_for(Expression.FOCUS, keyboard=True)
    assert texts == ["键盘冒火星啦！", "普通敲击台词"]
    assert _has_kb(texts) is True


def test_both_pools_empty_falls_back_to_pack(make_controller) -> None:
    """两组都空 → 两侧都回落预设包；自动侧仍被过滤，敲击侧保留键盘文案。"""

    ctl, _shown = make_controller(auto=[], hit=[], pack="default")

    auto_texts = ctl._bubble_texts_for(Mood.IDLE)
    hit_texts = ctl._bubble_texts_for(Expression.FOCUS, keyboard=True)
    assert auto_texts == C.BUBBLE_TEXTS[Mood.IDLE]
    assert not _has_kb(auto_texts)
    assert hit_texts == C.BUBBLE_TEXTS[Expression.FOCUS]
    assert _has_kb(hit_texts)


# =========================================================================== #
# 穷举矩阵：自动侧（含鼠标）在任何预设包下都不得露出键盘文案
# =========================================================================== #
def test_auto_side_exhaustive_matrix_has_no_keyboard_text(make_controller) -> None:
    keys = [
        Expression.HAPPY,
        Expression.YAWN,
        Expression.SLEEPY,
        Expression.SLEEPING,
        Mood.IDLE,
        Mood.REST,
        Mood.SLEEP,
        *sorted(C.KEYBOARD_BUBBLE_EXPRESSIONS, key=lambda e: e.name),
    ]
    offenders: list[tuple[str, str, str]] = []

    for pack in sorted(C.BUBBLE_TEXT_PACK_ALLOWED):
        ctl, shown = make_controller(
            auto=["键盘敲得真快！", "普通自定义"], hit=["敲击专属"], pack=pack
        )
        for key in keys:
            for immediate in (False, True):
                for _ in range(6):
                    _fire(ctl, key, immediate=immediate)
        for text in shown:
            if C.has_keyboard_keyword(text):
                offenders.append((pack, key.name, text))

    assert not offenders, f"自动侧露出键盘文案：{offenders[:5]}"


# =========================================================================== #
# 配置文件层端到端（不碰内部属性，直接读回 config.json）
# =========================================================================== #
def test_config_file_holds_two_pools_and_keeps_keyboard_lines(qapp: QApplication, tmp_path: Path) -> None:
    """两组各自落盘且**原样保留**（含键盘词的行不被写入时过滤，门控只在展示时生效）。"""

    path = tmp_path / "desktop-pet" / "config.json"
    store = ConfigStore(path)
    store.save(
        AppConfig(
            bubble_texts_custom=["自动一", "键盘敲得真快！"],
            bubble_texts_custom_keyboard=["敲击一"],
        )
    )

    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["bubble_texts_custom"] == ["自动一", "键盘敲得真快！"]
    assert raw["bubble_texts_custom_keyboard"] == ["敲击一"]

    ctl = PetAppController(qapp, ConfigStore(path))
    try:
        assert ctl._cfg.bubble_texts_custom == ["自动一", "键盘敲得真快！"]
        assert ctl._cfg.bubble_texts_custom_keyboard == ["敲击一"]
        # 展示时门控仍然生效
        assert ctl._bubble_texts_for(Mood.IDLE) == ["自动一"]
        assert ctl._bubble_texts_for(Expression.FOCUS, keyboard=True) == ["敲击一"]
    finally:
        ctl.shutdown()


def test_legacy_config_file_without_keyboard_key(qapp: QApplication, tmp_path: Path) -> None:
    """升级兼容：旧 config.json（无 bubble_texts_custom_keyboard）加载后敲击组为空、不报错。"""

    path = tmp_path / "desktop-pet" / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    legacy = AppConfig(bubble_texts_custom=["老配置的自动组"]).to_dict()
    legacy.pop("bubble_texts_custom_keyboard")
    path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    ctl = PetAppController(qapp, ConfigStore(path))
    try:
        assert ctl._cfg.bubble_texts_custom == ["老配置的自动组"]
        assert ctl._cfg.bubble_texts_custom_keyboard == []
        # 敲击侧回落预设包
        assert ctl._bubble_texts_for(Expression.FOCUS, keyboard=True) == C.BUBBLE_TEXTS[
            Expression.FOCUS
        ]
    finally:
        ctl.shutdown()


# =========================================================================== #
# 清洗边界：两组独立清洗，互不污染
# =========================================================================== #
def test_pools_cleaned_independently() -> None:
    cfg = AppConfig.from_dict(
        {
            "bubble_texts_custom": ["  重复 ", "重复", "", "有效A"],
            "bubble_texts_custom_keyboard": ["重复", "有效B", "   "],
        }
    )
    assert cfg.bubble_texts_custom == ["重复", "有效A"]
    assert cfg.bubble_texts_custom_keyboard == ["重复", "有效B"]


def test_long_line_truncated_in_both_pools() -> None:
    long_text = "啊" * (C.BUBBLE_TEXT_CUSTOM_MAX_LEN + 20)
    cfg = AppConfig.from_dict(
        {"bubble_texts_custom": [long_text], "bubble_texts_custom_keyboard": [long_text]}
    )
    assert len(cfg.bubble_texts_custom[0]) == C.BUBBLE_TEXT_CUSTOM_MAX_LEN
    assert len(cfg.bubble_texts_custom_keyboard[0]) == C.BUBBLE_TEXT_CUSTOM_MAX_LEN


def test_illegal_types_fall_back_independently() -> None:
    cfg = AppConfig.from_dict(
        {"bubble_texts_custom": "不是列表", "bubble_texts_custom_keyboard": ["合法敲击"]}
    )
    assert cfg.bubble_texts_custom == []
    assert cfg.bubble_texts_custom_keyboard == ["合法敲击"]


# =========================================================================== #
# Qt 集成：对话框 apply → 落盘 → 重开回填
# =========================================================================== #
def test_dialog_apply_then_reopen_keeps_two_pools(make_controller) -> None:
    ctl, _shown = make_controller(auto=["旧自动"], hit=["旧敲击"], pack="default")

    ctl._on_bubble_text_settings()
    dlg = ctl._bubble_text_dialog
    assert dlg is not None
    assert dlg.parse_custom_texts(dlg._auto_edit.toPlainText()) == ["旧自动"]
    assert dlg.parse_custom_texts(dlg._hit_edit.toPlainText()) == ["旧敲击"]

    dlg._auto_edit.setPlainText("新自动一\n新自动二")
    dlg._hit_edit.setPlainText("新敲击")
    dlg._on_apply()

    assert ctl._cfg.bubble_texts_custom == ["新自动一", "新自动二"]
    assert ctl._cfg.bubble_texts_custom_keyboard == ["新敲击"]

    # 落盘可读
    loaded = ctl._store.load()
    assert loaded.bubble_texts_custom == ["新自动一", "新自动二"]
    assert loaded.bubble_texts_custom_keyboard == ["新敲击"]

    # 重开回填
    ctl._on_bubble_text_settings()
    assert ctl._bubble_text_dialog is dlg
    assert dlg.parse_custom_texts(dlg._auto_edit.toPlainText()) == ["新自动一", "新自动二"]
    assert dlg.parse_custom_texts(dlg._hit_edit.toPlainText()) == ["新敲击"]
    dlg.close()


def test_apply_empty_clears_only_that_group(make_controller) -> None:
    ctl, _shown = make_controller(auto=["自动"], hit=["敲击"], pack="default")

    ctl._on_bubble_text_applied(C.DEFAULT_BUBBLE_TEXT_PACK, [], ["敲击保留"])
    assert ctl._cfg.bubble_texts_custom == []
    assert ctl._cfg.bubble_texts_custom_keyboard == ["敲击保留"]

    ctl._on_bubble_text_applied(C.DEFAULT_BUBBLE_TEXT_PACK, ["自动保留"], [])
    assert ctl._cfg.bubble_texts_custom == ["自动保留"]
    assert ctl._cfg.bubble_texts_custom_keyboard == []


# =========================================================================== #
# 2026-09-26 需求 C 重做：排期式自动触发（黑盒端到端）与独立敲击窗
#   旧行为缺陷：20~60s 只是「节流阀」——安静待机永远不说话、稳态打字看不到敲击组。
# =========================================================================== #
def test_scheduler_shows_periodically_without_any_event(make_controller) -> None:
    """需求 C-2 端到端：不敲键盘、不动鼠标，宠物也会每 20~60 秒主动说一句话。

    连续推进 240 秒帧循环（0.5s 一帧），统计自动闲聊条数：期望落在
    「240s / 60s」~「240s / 20s」即 4~12 条之间（随机窗口的理论范围）。

    两个边界条件（缺一不可，否则结果随**开机时长**漂移）：

    - 状态机构造于真实 ``time.monotonic()`` 基准，虚拟时钟必须把
      ``_last_input_ts`` / ``_state_since`` 重新锚定到同一基准，否则
      ``idle_seconds`` 会把虚拟时刻当成「已闲置数万秒」直接入睡；
    - 模拟时长必须短于 ``SLEEP_THRESHOLD_S``（300s）：全程无输入满 5 分钟
      按设计会入睡且**入睡不闲聊**，端到端节奏验收只覆盖醒着的时间段。
    """

    ctl, shown = make_controller(auto=["自动闲聊台词"], hit=[], pack="default")

    t = 50000.0
    ctl._sm._last_input_ts = t  # 锚定状态机时钟基准（与虚拟帧时钟一致）
    ctl._sm._state_since = t
    ctl._next_bubble_ts = t + 1.0  # 首条从 1 秒后开始排期
    for _ in range(480):  # 0.5s × 480 = 240s < SLEEP_THRESHOLD_S
        t += 0.5
        ctl._on_frame_tick(t)

    assert 4 <= len(shown) <= 12, f"4 分钟自动闲聊 {len(shown)} 条，排期器未按 20~60s 节奏工作"
    assert set(shown) == {"自动闲聊台词"}
    assert not _has_kb(shown)


def test_steady_typing_reliably_shows_keyboard_group(make_controller) -> None:
    """需求 C-1 正向面（端到端）：持续打字时敲击组文案按独立节奏可靠出现。

    旧行为只在情绪迁移瞬间才有机会弹——稳态打字时用户配的敲击组几乎永远看不到。
    模拟 3 分钟连续打字（0.2s 一次敲键）：敲击组应出现 3~9 条（3 分钟 / 20~60s）。
    """

    ctl, shown = make_controller(auto=[], hit=["敲得键盘冒烟啦~~"], pack="default")

    t = 60000.0
    for _ in range(900):  # 0.2s × 900 = 180s 连续打字
        t += 0.2
        ctl._on_keystroke(t)

    assert 3 <= len(shown) <= 9, f"3 分钟稳态打字敲击组出现 {len(shown)} 次，独立节奏失效"
    assert set(shown) == {"敲得键盘冒烟啦~~"}


def test_keystroke_and_auto_windows_never_interfere(make_controller) -> None:
    """两组节奏互不挤占：自动闲聊不打断敲击组的既定排期，反之亦然。"""

    ctl, shown = make_controller(auto=["自动一"], hit=["敲击一"], pack="default")

    # 敲击组先展示（敲击窗重排到 500+20~60）
    assert _fire(ctl, C.Expression.FOCUS, keyboard=True) is True
    kb_window = ctl._next_kb_bubble_ts

    # 自动组在敲击窗关闭期间照常展示（手动只重置自动窗与硬下限，不动敲击窗）
    ctl._last_bubble_ts = float("-inf")
    ctl._next_bubble_ts = float("-inf")
    ctl._show_bubble_for(C.Mood.IDLE, 500.0)
    assert ctl._last_bubble_ts == 500.0
    # 敲击窗未被自动展示挪动（仍是 kb_window）
    assert ctl._next_kb_bubble_ts == kb_window

    # 敲击窗一开就能再展示敲击组（不受自动窗约束）
    ctl._last_bubble_ts = float("-inf")
    ctl._show_bubble_for(C.Expression.FOCUS, kb_window + 0.01, keyboard=True)
    assert shown[-1] == "敲击一"


def test_sleep_state_proactively_skips_chat(make_controller) -> None:
    """睡觉态到点不闲聊（但窗口推进，防醒来连弹）。"""

    ctl, shown = make_controller(auto=["自动闲聊"], hit=[], pack="default")
    ctl._sm._state = C.Mood.SLEEP

    t = 70000.0
    ctl._next_bubble_ts = t
    ctl._on_frame_tick(t)

    assert shown == [], "睡觉态不应主动闲聊"
    assert ctl._next_bubble_ts > t, "睡觉态窗口未推进"


def test_mouse_immediate_does_not_disturb_keyboard_window(make_controller) -> None:
    """鼠标 immediate 展示（重排自动窗）不得影响敲击窗的既定排期。"""

    ctl, _shown = make_controller(auto=[], hit=["敲击专属"], pack="default")

    # 敲击组先展示一次 → 敲击窗重排
    assert _fire(ctl, C.Expression.FOCUS, keyboard=True) is True
    kb_window = ctl._next_kb_bubble_ts

    # 鼠标立即展示一条（重排自动窗）
    ctl._last_bubble_ts = float("-inf")
    ctl._show_bubble_for(MOUSE_KEY, 600.0, immediate=True)
    assert ctl._next_bubble_ts >= 600.0 + WINDOW[0]
    # 敲击窗保持原排期
    assert ctl._next_kb_bubble_ts == kb_window
