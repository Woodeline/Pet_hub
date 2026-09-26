"""ui.bubble_text_dialog 气泡台词设置对话框单元测试。

覆盖：解析清洗规则（与 config coerce 同规）、**两组自定义池**（2026-09-26 需求 C-4：
自动触发组 / 敲击键盘组）、applied 信号负载、load_state 回填、预设包下拉选项完整性。
不测视觉布局。
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QGroupBox

from desktop_pet.core import constants as C
from desktop_pet.ui.bubble_text_dialog import BubbleTextDialog


def test_parse_custom_texts_cleans(qtbot) -> None:  # noqa: ARG001
    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    raw = "  摸摸我呀~ \n\n   \n加油鸭！\n摸摸我呀~\n" + "啊" * 100
    texts = dialog.parse_custom_texts(raw)
    # strip + 去空行 + 去重；超长行截断到 MAX_LEN
    assert texts[0] == "摸摸我呀~"
    assert texts[1] == "加油鸭！"
    assert texts[2] == "啊" * C.BUBBLE_TEXT_CUSTOM_MAX_LEN
    assert len(texts) == 3
    assert all(len(t) <= C.BUBBLE_TEXT_CUSTOM_MAX_LEN for t in texts)


def test_parse_custom_texts_respects_count_limit(qtbot) -> None:  # noqa: ARG001
    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    raw = "\n".join(f"台词{i}" for i in range(C.BUBBLE_TEXT_CUSTOM_MAX_COUNT + 10))
    assert len(dialog.parse_custom_texts(raw)) == C.BUBBLE_TEXT_CUSTOM_MAX_COUNT


def test_parse_empty_means_not_enabled(qtbot) -> None:  # noqa: ARG001
    """空编辑区 = 该组未配置（回落预设包），解析结果为空列表。"""

    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    assert dialog.parse_custom_texts("\n  \n") == []


# --------------------------------------------------------------------------- #
# 两组自定义池（需求 C-4）
# --------------------------------------------------------------------------- #
def test_two_groups_have_own_edit_areas(qtbot) -> None:  # noqa: ARG001
    """两组各有独立编辑区，构造时分别回填，互不串味。"""

    dialog = BubbleTextDialog(
        pack="default",
        custom_texts=["自动组台词A"],
        custom_keyboard_texts=["敲击组台词B", "键盘台词C"],
    )
    qtbot.addWidget(dialog)

    assert dialog.parse_custom_texts(dialog._auto_edit.toPlainText()) == ["自动组台词A"]
    assert dialog.parse_custom_texts(dialog._hit_edit.toPlainText()) == ["敲击组台词B", "键盘台词C"]


def test_two_groups_are_labelled_in_ui(qtbot) -> None:  # noqa: ARG001
    """UI 上必须能看出两组分别对应哪种触发来源（需求 C-4 的可见性要求）。"""

    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    titles = [box.title() for box in dialog.findChildren(QGroupBox)]

    assert any("自动触发组" in t for t in titles), f"缺少自动触发组标题：{titles}"
    assert any("敲击键盘组" in t for t in titles), f"缺少敲击键盘组标题：{titles}"


def test_auto_group_count_warns_about_keyboard_lines(qtbot) -> None:  # noqa: ARG001
    """自动组含键盘关键字的行会被提示「不会自动触发」（避免用户误配置后困惑）。"""

    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)

    dialog._auto_edit.setPlainText("摸摸我呀~\n键盘敲得真快！")
    label = dialog._auto_count_label.text()
    assert "2 条" in label
    assert "1 条含键盘关键字" in label, f"未提示被过滤条数：{label}"


def test_keyboard_group_count_label_mentions_keystroke(qtbot) -> None:  # noqa: ARG001
    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)

    dialog._hit_edit.setPlainText("敲吧敲吧~")
    assert "1 条" in dialog._hit_count_label.text()
    assert "敲键盘" in dialog._hit_count_label.text()


def test_counts_are_independent_between_groups(qtbot) -> None:  # noqa: ARG001
    """清空自动组不影响敲击组计数提示。"""

    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    dialog._auto_edit.setPlainText("自动一")
    dialog._hit_edit.setPlainText("敲击一\n敲击二")

    dialog._auto_edit.setPlainText("")
    assert "未启用" in dialog._auto_count_label.text()
    assert "2 条" in dialog._hit_count_label.text()


# --------------------------------------------------------------------------- #
# applied 信号 / load_state
# --------------------------------------------------------------------------- #
def test_applied_signal_payload(qtbot) -> None:  # noqa: ARG001
    """点击「应用」→ applied 携带 (包名, 自动组, 敲击组) 并关闭。"""

    dialog = BubbleTextDialog(pack="gentle", custom_texts=["我在呢~"])
    qtbot.addWidget(dialog)

    payload: list[tuple] = []
    dialog.applied.connect(lambda p, a, k: payload.append((p, a, k)))
    dialog._auto_edit.setPlainText(" 摸摸我呀~ \n加油鸭！")
    dialog._hit_edit.setPlainText(" 键盘敲得真快！ \n哒哒哒~")
    dialog._on_apply()

    assert len(payload) == 1
    pack, auto_texts, hit_texts = payload[0]
    assert pack == "gentle"
    assert auto_texts == ["摸摸我呀~", "加油鸭！"]
    assert hit_texts == ["键盘敲得真快！", "哒哒哒~"]
    assert not dialog.isVisible()  # accept() 已关闭


def test_applied_emits_empty_when_group_cleared(qtbot) -> None:  # noqa: ARG001
    """清空编辑区 = 该组回落预设包（发空列表，而不是发旧值）。"""

    dialog = BubbleTextDialog(custom_texts=["旧的"], custom_keyboard_texts=["旧的敲击"])
    qtbot.addWidget(dialog)

    payload: list[tuple] = []
    dialog.applied.connect(lambda p, a, k: payload.append((p, a, k)))
    dialog._auto_edit.setPlainText("")
    dialog._hit_edit.setPlainText("")
    dialog._on_apply()

    assert payload == [(C.DEFAULT_BUBBLE_TEXT_PACK, [], [])]


def test_load_state_refills_ui(qtbot) -> None:  # noqa: ARG001
    """load_state 按最新配置回填两组（重开对话框拿最新值的路径）。"""

    dialog = BubbleTextDialog(pack="default", custom_texts=[])
    qtbot.addWidget(dialog)
    dialog.load_state("energy", ["台词A", "台词B"], ["敲击C"])
    assert dialog._pack_combo.currentData() == "energy"
    assert dialog.parse_custom_texts(dialog._auto_edit.toPlainText()) == ["台词A", "台词B"]
    assert dialog.parse_custom_texts(dialog._hit_edit.toPlainText()) == ["敲击C"]


def test_load_state_keyboard_group_defaults_to_empty(qtbot) -> None:  # noqa: ARG001
    """向后兼容：只传两组参数的老调用方式仍可用（敲击组清空）。"""

    dialog = BubbleTextDialog(pack="default", custom_texts=["自动一"])
    qtbot.addWidget(dialog)
    dialog.load_state("gentle", ["换了内容"])
    assert dialog._pack_combo.currentData() == "gentle"
    assert dialog.parse_custom_texts(dialog._auto_edit.toPlainText()) == ["换了内容"]
    assert dialog.parse_custom_texts(dialog._hit_edit.toPlainText()) == []


def test_pack_combo_lists_all_packs(qtbot) -> None:  # noqa: ARG001
    """下拉必须覆盖全部白名单包名（default + 两个预设包）。"""

    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    data = [dialog._pack_combo.itemData(i) for i in range(dialog._pack_combo.count())]
    assert set(data) == set(C.BUBBLE_TEXT_PACK_ALLOWED)
