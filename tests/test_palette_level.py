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
    "spring_festival",
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
    """``COLORS`` 键集与值**全等**（中性化改版锚值，防静默漂移）。

    宠物本体色（ink/blush/mouse_*/glow_*）与毛色渐变保持原值；仅气泡 chrome、
    按钮条、状态标签、生词本配色改为中性扁平（白底/近黑/浅灰/绿点缀）。
    """

    assert C.COLORS == {
        "ink": "#141414",
        "blush": "#FFB3C7",
        "white": "#FFFFFF",
        "mouse_body": "#3A3A3A",
        "mouse_hi": "#8A8A8A",
        "bubble_bg": "#FFFFFF",
        "bubble_text": "#1F2328",
        "glow_yellow": "#FFD08A",
        "glow_blue": "#B9D4E8",
        "warm_brown": "#3D444D",
        "bubble_sub_text": "#5A626C",
        "bubble_faint_text": "#98A2AD",
        "vocab_bg": "#FFFFFF",
        "vocab_text": "#1F2328",
        "vocab_level_tag": "#5A626C",
        "bubble_gradient_hi": "#FFFFFF",
        "jp_button_primary_bg": "#3FB950",
        "jp_button_primary_text": "#FFFFFF",
        "jp_button_primary_hover": "#53C463",
        "jp_button_primary_pressed": "#349A44",
        "jp_button_secondary_border": "#C9CDD3",
        "jp_button_secondary_text": "#1F2328",
        "jp_button_secondary_hover": "#EEF0F3",
        "jp_button_bar_bg": "#FFFFFF",
        "log_status_mastered": "#3FB950",
        "log_status_vocab": "#4C8DDA",
        "log_status_unprocessed": "#98A2AD",
        "bubble_shadow": "#C9CDD3",
        "bubble_divider": "#E3E6EA",
        "bubble_gradient_bottom": "#F5F6F8",
        "jp_level_chip_bg": "#5A626C",
        "jp_level_chip_text": "#FFFFFF",
        # 气泡双层描边（贴纸风）
        "bubble_border": "#D8DDE3",
        "bubble_halo": "#FFFFFF",
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


# --------------------------------------------------------------------------- #
# 4. BODY_GRADIENT_STOPS 5 个停靠点字面量锚点（补齐 B1 色值漂移守卫，C3）
# --------------------------------------------------------------------------- #
def test_body_gradient_stops_literal_values() -> None:
    """锁定 B1 降饱和终档的 5 个停靠点（位置 + 色值，**字面量期望**）。

    这补齐了 B1 的遗留缺口：此前 0.00 / 0.25 / 0.75 三个停靠点的**色值**仅有结构 /
    合法 hex 断言（`test_body_gradient_and_outline_defined` 不锁色值），只有 0.50 端点
    被 `glow_for_theme` 间接覆盖。本断言以**全等**方式锁定全部 5 个位置与色值 ——
    刻意**不引用** `C.BODY_GRADIENT_STOPS` 自身拼期望（防自引用假绿）。
    """

    assert C.BODY_GRADIENT_STOPS == (
        (0.00, "#ACE4A5"),
        (0.25, "#FDF7AF"),
        (0.50, "#FBC9A5"),
        (0.75, "#F9ABD3"),
        (1.00, "#ACD6EC"),
    )


# --------------------------------------------------------------------------- #
# 5. ui_accent_for_theme（UI 中性化改版：主题点缀色派生）
# --------------------------------------------------------------------------- #
def test_ui_accent_default_and_unknown_fall_back_to_neutral() -> None:
    """default 主题与未知名称回落中性主色（默认界面保持黑白灰）。"""

    from desktop_pet.core.theme import ui_accent_for_theme

    assert ui_accent_for_theme("default") == C.SEMANTIC_COLORS["primary"]
    assert ui_accent_for_theme("不存在的皮肤") == C.SEMANTIC_COLORS["primary"]
    assert ui_accent_for_theme("") == C.SEMANTIC_COLORS["primary"]


def test_ui_accent_seasons_are_distinct_and_readable() -> None:
    """四季 + 春节点缀色：合法 hex、互不相同、与中性主色不同。"""

    from desktop_pet.core.theme import ui_accent_for_theme

    accents = {
        theme: ui_accent_for_theme(theme)
        for theme in ("spring", "summer", "autumn", "winter", "spring_festival")
    }
    for theme, accent in accents.items():
        assert _HEX_RE.match(accent), f"{theme} 点缀色非法：{accent}"
        assert accent != C.SEMANTIC_COLORS["primary"], f"{theme} 点缀色不应回落中性"
    assert len(set(accents.values())) == len(accents), f"点缀色存在重复：{accents}"


def test_ui_accent_lightness_capped_for_white_background() -> None:
    """点缀色明度被钳制（白底可读）：取最深停靠点压暗后 R/G/B 不会过亮。"""

    import colorsys

    from desktop_pet.core.theme import ui_accent_for_theme

    for theme in ("spring", "summer", "autumn", "winter", "spring_festival"):
        hexv = ui_accent_for_theme(theme)
        r, g, b = (int(hexv[i:i + 2], 16) / 255.0 for i in (1, 3, 5))
        _h, l, _s = colorsys.rgb_to_hls(r, g, b)
        assert l <= 0.45, f"{theme} 点缀色过亮（l={l:.2f}），白底可读性不足"
