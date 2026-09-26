"""app 层情绪气泡台词自定义：来源优先级 + 设置落地。

覆盖 controller._bubble_texts_for 的**按触发源选池**三级来源
（自定义池 > 预设台词包 > 内置文案表）与「气泡文案」对话框确认后的配置落地。

分组门控的完整行为（键盘关键字过滤、敲击组专属、鼠标路径、组间独立）
见 tests/test_bubble_text_groups.py。单词泡泡（show_word）路径不在本文件范围内
——它不受台词配置影响，由 test_jp_ui / test_jp_memory_ui 守护。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig, ConfigStore
from desktop_pet.core.constants import Expression, Mood


@pytest.fixture()
def controller(qtbot, tmp_path: Path):
    """装配一个最小 controller（监听关闭，不真正 show 弹窗打扰）。"""

    from desktop_pet.app.controller import PetAppController

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(AppConfig(listen_enabled=False))
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    ctl = PetAppController(app, store)
    qtbot.addWidget(ctl._window)
    yield ctl, store
    ctl.shutdown()


# --------------------------------------------------------------------------- #
# 1. 台词来源三级优先级（**自动触发侧**；敲击侧见 test_bubble_text_groups.py）
# --------------------------------------------------------------------------- #
def test_auto_custom_pool_overrides_everything(controller) -> None:
    """自动组自定义池非空（且不含键盘关键字）→ 对所有自动侧情绪统一使用，预设包被跳过。"""

    ctl, _store = controller
    ctl._cfg.bubble_texts_custom = ["摸摸我呀~", "加油鸭！"]
    ctl._cfg.bubble_text_pack = "energy"

    for key in (Expression.HAPPY, Mood.IDLE, Mood.REST, Mood.SLEEP):
        assert ctl._bubble_texts_for(key) == ["摸摸我呀~", "加油鸭！"]


def test_pack_texts_win_for_covered_keys(controller) -> None:
    """无自定义 → 预设包覆盖的键用包文案（energy 覆盖 HAPPY）。"""

    ctl, _store = controller
    ctl._cfg.bubble_texts_custom = []
    ctl._cfg.bubble_text_pack = "energy"
    assert ctl._bubble_texts_for(Expression.HAPPY) == C.BUBBLE_TEXT_PACKS["energy"][Expression.HAPPY]


def test_pack_falls_back_to_builtin_for_uncovered_keys(controller) -> None:
    """预设包未覆盖的键回落内置 BUBBLE_TEXTS（energy 未覆盖 Mood.SLEEP）。"""

    ctl, _store = controller
    ctl._cfg.bubble_text_pack = "energy"
    assert Mood.SLEEP not in C.BUBBLE_TEXT_PACKS["energy"]
    assert ctl._bubble_texts_for(Mood.SLEEP) == C.BUBBLE_TEXTS[Mood.SLEEP]


def test_default_pack_equals_builtin_texts(controller) -> None:
    """default 包 = 内置文案表本身的行为。"""

    ctl, _store = controller
    ctl._cfg.bubble_texts_custom = []
    ctl._cfg.bubble_text_pack = "default"
    assert ctl._bubble_texts_for(Expression.HAPPY) == C.BUBBLE_TEXTS[Expression.HAPPY]


def test_keyboard_pool_used_only_for_keyboard_trigger(controller) -> None:
    """敲击组只对 keyboard=True 生效；同一次调用换成自动侧则看不到它。"""

    ctl, _store = controller
    ctl._cfg.bubble_texts_custom = []
    ctl._cfg.bubble_texts_custom_keyboard = ["敲吧敲吧~"]

    assert ctl._bubble_texts_for(Mood.IDLE, keyboard=True) == ["敲吧敲吧~"]
    assert ctl._bubble_texts_for(Mood.IDLE) != ["敲吧敲吧~"]


def test_word_bubble_path_untouched_by_text_config(controller) -> None:
    """台词配置不影响单词泡泡：show_word 的五字段赋值路径与配置值无关。"""

    ctl, _store = controller
    ctl._cfg.bubble_texts_custom = ["自定义台词"]
    ctl._cfg.bubble_texts_custom_keyboard = ["键盘自定义台词"]
    ctl._cfg.bubble_text_pack = "gentle"

    from desktop_pet.core.vocabulary import VocabEntry

    entry = VocabEntry(
        id="n5-0001", level="N5", word="食べる", kana="たべる",
        translation="吃", meaning="进食",
    )
    ctl._bubble.show_word(entry, 30.0)
    assert ctl._bubble._line_word == "食べる"
    assert ctl._bubble._line_kana == "たべる"
    assert ctl._bubble._line_translation == "吃"
    assert ctl._bubble._line_meaning == "进食"
    ctl._bubble.hide_bubble()


# --------------------------------------------------------------------------- #
# 2. 设置落地
# --------------------------------------------------------------------------- #
def test_applied_writes_config_and_persists(controller) -> None:
    """对话框确认 → cfg 更新 + 落盘；再 load 能读到（即改即生效的数据前提）。"""

    ctl, store = controller
    ctl._on_bubble_text_applied("energy", ["你好呀", "  你好呀 ", ""], ["敲敲敲", ""])
    assert ctl._cfg.bubble_text_pack == "energy"
    assert ctl._cfg.bubble_texts_custom == ["你好呀"]
    assert ctl._cfg.bubble_texts_custom_keyboard == ["敲敲敲"]

    loaded = store.load()
    assert loaded.bubble_text_pack == "energy"
    assert loaded.bubble_texts_custom == ["你好呀"]
    assert loaded.bubble_texts_custom_keyboard == ["敲敲敲"]


def test_applied_updates_both_pools_in_one_transaction(controller) -> None:
    """两组一次事务写入：清空一组不影响另一组被正确写入。"""

    ctl, _store = controller
    ctl._on_bubble_text_applied(C.DEFAULT_BUBBLE_TEXT_PACK, [], ["只剩敲击组"])
    assert ctl._cfg.bubble_texts_custom == []
    assert ctl._cfg.bubble_texts_custom_keyboard == ["只剩敲击组"]


def test_applied_ignores_illegal_pack(controller) -> None:
    """非法包名不写入（coerce 已拦一层，此处守 controller 槽的防线）。"""

    ctl, _store = controller
    ctl._on_bubble_text_applied("banana", [], [])
    assert ctl._cfg.bubble_text_pack == C.DEFAULT_BUBBLE_TEXT_PACK


def test_dialog_singleton_refills_from_config(controller) -> None:
    """打开对话框：单例创建 + 回填两组当前配置；二次打开复用同一实例。"""

    ctl, _store = controller
    ctl._cfg.bubble_text_pack = "gentle"
    ctl._cfg.bubble_texts_custom = ["慢慢来~"]
    ctl._cfg.bubble_texts_custom_keyboard = ["敲我别急~"]

    ctl._on_bubble_text_settings()
    first = ctl._bubble_text_dialog
    assert first is not None
    assert first._pack_combo.currentData() == "gentle"
    assert first.parse_custom_texts(first._auto_edit.toPlainText()) == ["慢慢来~"]
    assert first.parse_custom_texts(first._hit_edit.toPlainText()) == ["敲我别急~"]

    ctl._cfg.bubble_texts_custom = ["换了内容"]
    ctl._cfg.bubble_texts_custom_keyboard = ["换了敲击"]
    ctl._on_bubble_text_settings()
    assert ctl._bubble_text_dialog is first
    assert first.parse_custom_texts(first._auto_edit.toPlainText()) == ["换了内容"]
    assert first.parse_custom_texts(first._hit_edit.toPlainText()) == ["换了敲击"]
    first.close()
