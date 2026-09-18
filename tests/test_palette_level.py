"""色彩微调回归测试（阶段 B1：光晕随主题派生 + 道具描边分层）。

- ``PROP_OUTLINE``（字面量 / 合法 hex / ``__all__`` 登记 / 与 ink 有别）。
- ``glow_for_theme``：7 套皮肤 × {清醒, 睡觉} 输出合法 hex、彼此不同（不机械取端点）。
- 回归：``COLORS`` 键值全等未变、``SEMANTIC_COLORS`` 键集未变（**字面量期望**，
  不引用被测常量自身拼期望）。
"""

from __future__ import annotations

import re

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.theme import glow_for_theme
from desktop_pet.ui.pet_renderer import PetRenderer

_ALL_THEMES = (
    "default", "spring", "summer", "autumn", "winter",
    "spring_festival", "christmas",
)

_HEX_RE = re.compile(r"^#[0-9A-F]{6}$")


# --------------------------------------------------------------------------- #
# 1. PROP_OUTLINE（道具描边分层，G1）
# --------------------------------------------------------------------------- #
def test_prop_outline_constant_is_literal_value() -> None:
    assert C.PROP_OUTLINE == "#4A4A4A"


def test_prop_outline_is_valid_uppercase_hex() -> None:
    assert _HEX_RE.match(C.PROP_OUTLINE), f"非法色值：{C.PROP_OUTLINE!r}"


def test_prop_outline_registered_in_all() -> None:
    assert "PROP_OUTLINE" in C.__all__


def test_prop_outline_differs_from_ink() -> None:
    assert C.PROP_OUTLINE != C.COLORS["ink"]


def test_renderer_prop_pen_uses_prop_outline() -> None:
    """渲染器道具笔用 ``PROP_OUTLINE``，主体笔仍用 ``ink``（描边层级差落地）。"""

    renderer = PetRenderer()
    assert renderer._outline_prop.color().name().upper() == C.PROP_OUTLINE
    assert renderer._outline.color().name().upper() == "#141414"


# --------------------------------------------------------------------------- #
# 2. glow_for_theme（光晕随主题派生）
# --------------------------------------------------------------------------- #
def test_glow_for_theme_default_literal_values() -> None:
    """默认皮肤字面量锚点（锁定派生公式：清醒取暖端 / 睡觉取冷端）。

    默认皮肤色值随 B1-2 降饱和而变，故本锚点亦随之更新（其余 6 套皮肤色值稳定）。
    """

    assert glow_for_theme("default", False) == "#EACCB7"
    assert glow_for_theme("default", True) == "#CCDBE2"


@pytest.mark.parametrize("name", _ALL_THEMES)
def test_glow_for_theme_valid_hex(name: str) -> None:
    for sleeping in (False, True):
        value = glow_for_theme(name, sleeping)
        assert _HEX_RE.match(value), f"{name}(sleeping={sleeping}) 非法色值：{value!r}"


@pytest.mark.parametrize("name", _ALL_THEMES)
def test_glow_for_theme_awake_differs_from_sleeping(name: str) -> None:
    assert glow_for_theme(name, False) != glow_for_theme(name, True)


def test_glow_for_theme_awake_values_pairwise_distinct() -> None:
    values = [glow_for_theme(name, False) for name in _ALL_THEMES]
    assert len(set(values)) == len(_ALL_THEMES), f"清醒光晕存在重复：{values}"


def test_glow_for_theme_sleeping_values_pairwise_distinct() -> None:
    values = [glow_for_theme(name, True) for name in _ALL_THEMES]
    assert len(set(values)) == len(_ALL_THEMES), f"睡觉光晕存在重复：{values}"


def test_glow_for_theme_unknown_falls_back_to_default() -> None:
    assert glow_for_theme("banana", False) == glow_for_theme("default", False)
    assert glow_for_theme("", True) == glow_for_theme("default", True)


# --------------------------------------------------------------------------- #
# 3. 回归：既有配色未被动过
# --------------------------------------------------------------------------- #
def test_colors_dict_unchanged_literal() -> None:
    """``COLORS`` 键集与值**全等未变**（字面量期望，防降饱和误伤既有语义色）。"""

    assert C.COLORS == {
        "ink": "#141414",
        "blush": "#FFB3C7",
        "white": "#FFFFFF",
        "mouse_body": "#3A3A3A",
        "mouse_hi": "#8A8A8A",
        "bubble_bg": "#FFFDF8",
        "bubble_text": "#7A5A42",
        "glow_yellow": "#FFD08A",
        "glow_blue": "#B9D4E8",
        "warm_brown": "#8B6B4F",
        "bubble_sub_text": "#9C8570",
        "bubble_faint_text": "#B7A99A",
        "vocab_bg": "#FFFDF8",
        "vocab_text": "#5A4636",
        "vocab_level_tag": "#7A9E7E",
        "bubble_gradient_hi": "#FFFFFF",
        "jp_button_primary_bg": "#7A9E7E",
        "jp_button_primary_text": "#FFFFFF",
        "jp_button_primary_hover": "#8FB090",
        "jp_button_primary_pressed": "#6B8E6F",
        "jp_button_secondary_border": "#9C8570",
        "jp_button_secondary_text": "#7A5A42",
        "jp_button_secondary_hover": "#F3EAE0",
        "jp_button_bar_bg": "#FFFDF8",
        "log_status_mastered": "#7A9E7E",
        "log_status_vocab": "#5B8DB8",
        "log_status_unprocessed": "#B7A99A",
        "bubble_shadow": "#C9B8A6",
        "bubble_divider": "#EFE3D4",
        "bubble_gradient_bottom": "#F7EEDF",
        "jp_level_chip_bg": "#7A9E7E",
        "jp_level_chip_text": "#FFFFFF",
    }


def test_semantic_colors_keyset_unchanged_literal() -> None:
    """``SEMANTIC_COLORS`` 键集未变（字面量期望）。"""

    assert set(C.SEMANTIC_COLORS) == {
        "primary", "primary_hover", "primary_pressed",
        "success", "success_hover", "success_pressed",
        "info", "warning", "muted",
        "destructive", "destructive_hover",
        "surface", "surface_alt", "border",
        "text_primary", "text_secondary", "text_faint",
    }


def test_glow_semantic_colors_untouched() -> None:
    """既有光晕语义色不许改（它们是语义色，不是新派生色的落点）。"""

    assert C.COLORS["glow_yellow"] == "#FFD08A"
    assert C.COLORS["glow_blue"] == "#B9D4E8"
