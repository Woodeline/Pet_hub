"""ui.bubble_text_dialog 气泡台词设置对话框单元测试。

覆盖：解析清洗规则（与 config coerce 同规）、applied 信号负载、load_state 回填、
预设包下拉选项完整性。不测视觉布局。
"""

from __future__ import annotations

import pytest

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
    """空编辑区 = 不启用自定义（回落预设包），解析结果为空列表。"""

    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    assert dialog.parse_custom_texts("\n  \n") == []


def test_applied_signal_payload(qtbot) -> None:  # noqa: ARG001
    """点击「应用」→ applied 信号携带 (包名, 清洗后自定义列表) 并关闭。"""

    dialog = BubbleTextDialog(pack="gentle", custom_texts=["我在呢~"])
    qtbot.addWidget(dialog)

    payload: list[tuple] = []
    dialog.applied.connect(lambda p, t: payload.append((p, t)))
    dialog._custom_edit.setPlainText(" 摸摸我呀~ \n加油鸭！")
    dialog._on_apply()

    assert len(payload) == 1
    pack, texts = payload[0]
    assert pack == "gentle"
    assert texts == ["摸摸我呀~", "加油鸭！"]
    assert not dialog.isVisible()  # accept() 已关闭


def test_load_state_refills_ui(qtbot) -> None:  # noqa: ARG001
    """load_state 按最新配置回填（重开对话框拿最新值的路径）。"""

    dialog = BubbleTextDialog(pack="default", custom_texts=[])
    qtbot.addWidget(dialog)
    dialog.load_state("energy", ["台词A", "台词B"])
    assert dialog._pack_combo.currentData() == "energy"
    assert dialog.parse_custom_texts(dialog._custom_edit.toPlainText()) == ["台词A", "台词B"]


def test_pack_combo_lists_all_packs(qtbot) -> None:  # noqa: ARG001
    """下拉必须覆盖全部白名单包名（default + 两个预设包）。"""

    dialog = BubbleTextDialog()
    qtbot.addWidget(dialog)
    data = [dialog._pack_combo.itemData(i) for i in range(dialog._pack_combo.count())]
    assert set(data) == set(C.BUBBLE_TEXT_PACK_ALLOWED)
