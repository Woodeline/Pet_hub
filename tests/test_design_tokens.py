"""设计 token 地基（UI 视觉升级 P0）回归测试。

守护 ``core.constants`` 新增的四张 design token 表：

- ``SEMANTIC_COLORS`` / ``SPACING`` / ``FONT_SIZE`` / ``RADIUS`` 可导入、键名与计划一致。
- 语义色与既有 ``COLORS`` 的**映射关系**（值相等）——保证「改色不改结构」。
- 色值均合法 ``#RRGGBB``；``warning`` 与 ``info`` 解耦（生词 ≠ 信息）。
- 刻度（间距 / 字号 / 圆角）为正整数；字号严格单调递减。
- ``COLORS`` 的**键集合**未被本阶段改动（``test_color_palette_matches_prd`` 仍负责全等）。

本阶段为纯加法：只新增 token，不改既有色键值、不引入任何 Qt 依赖。
"""

from __future__ import annotations

import re

import pytest

from desktop_pet.core import constants as C

# 合法色值形如 #RRGGBB（大小写不限，此处统一大写比较）。
_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


# --------------------------------------------------------------------------- #
# 1. 四张表可导入，且键集合与设计计划一致
# --------------------------------------------------------------------------- #
def test_semantic_colors_keys_match_plan() -> None:
    """``SEMANTIC_COLORS`` 键集合与计划逐字一致。"""

    expected = {
        "primary", "primary_hover", "primary_pressed",
        "success", "success_hover", "success_pressed",
        "info", "warning", "muted",
        "destructive", "destructive_hover",
        "surface", "surface_alt", "border",
        "text_primary", "text_secondary", "text_faint",
    }
    assert set(C.SEMANTIC_COLORS) == expected


def test_spacing_keys_match_plan() -> None:
    """``SPACING`` 键集合与计划一致。"""

    assert set(C.SPACING) == {"xs", "sm", "md", "lg", "xl"}


def test_font_size_keys_match_plan() -> None:
    """``FONT_SIZE`` 键集合与计划一致。"""

    assert set(C.FONT_SIZE) == {"display", "title", "body", "caption", "small"}


def test_radius_keys_match_plan() -> None:
    """``RADIUS`` 键集合与计划一致。"""

    assert set(C.RADIUS) == {"sm", "md", "lg", "pill"}


# --------------------------------------------------------------------------- #
# 2. 语义色 ↔ 既有 COLORS 的映射关系（值相等）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "semantic_key,legacy_key",
    [
        ("primary", "bubble_text"),
        ("primary_hover", "warm_brown"),
        ("success", "jp_button_primary_bg"),
        ("success", "log_status_mastered"),
        ("success_hover", "jp_button_primary_hover"),
        ("success_pressed", "jp_button_primary_pressed"),
        ("info", "log_status_vocab"),
        ("muted", "log_status_unprocessed"),
        ("surface", "bubble_bg"),
        ("surface", "jp_button_bar_bg"),
        ("surface_alt", "bubble_gradient_bottom"),
        ("border", "bubble_divider"),
        ("text_primary", "vocab_text"),
        ("text_secondary", "bubble_sub_text"),
        ("text_faint", "bubble_faint_text"),
    ],
)
def test_semantic_color_maps_to_legacy_palette(semantic_key: str, legacy_key: str) -> None:
    """语义色必须与既有 ``COLORS`` 对应键**值相等**（迁移期单一事实源一致）。"""

    assert C.SEMANTIC_COLORS[semantic_key] == C.COLORS[legacy_key]


def test_primary_equals_bubble_text_literal() -> None:
    """品牌主色即气泡正文色 ``#7A5A42``（计划给定值，防漂移）。"""

    assert C.SEMANTIC_COLORS["primary"] == "#7A5A42"
    assert C.SEMANTIC_COLORS["primary"] == C.COLORS["bubble_text"]


# --------------------------------------------------------------------------- #
# 3. 所有色值为合法 #RRGGBB
# --------------------------------------------------------------------------- #
def test_semantic_colors_are_valid_hex() -> None:
    """``SEMANTIC_COLORS`` 每个值都是合法 ``#RRGGBB``（可被 16 进制解析）。"""

    for key, value in C.SEMANTIC_COLORS.items():
        assert isinstance(value, str), f"{key} 非字符串：{value!r}"
        assert value.startswith("#"), f"{key} 缺少 # 前缀：{value!r}"
        assert len(value) == 7, f"{key} 长度非 7：{value!r}"
        assert _HEX_RE.match(value), f"{key} 非法色值：{value!r}"
        int(value[1:], 16)  # 必须可解析，否则抛 ValueError 使该用例失败


# --------------------------------------------------------------------------- #
# 4. warning 与 info 解耦
# --------------------------------------------------------------------------- #
def test_warning_decoupled_from_info() -> None:
    """生词状态（warning，琥珀）必须与信息状态（info，蓝）**值不相等**。"""

    assert C.SEMANTIC_COLORS["warning"] != C.SEMANTIC_COLORS["info"]
    # 同时确认它不再沿用旧的「生词=蓝」历史色（log_status_vocab 为蓝）。
    assert C.SEMANTIC_COLORS["warning"] != C.COLORS["log_status_vocab"]


# --------------------------------------------------------------------------- #
# 5. 刻度表：正整数 / 单调递减 / 去重
# --------------------------------------------------------------------------- #
def test_spacing_values_positive_and_unique() -> None:
    """间距刻度全为正整数、彼此不重复，且满足 4px 基线（``sm/lg/xl`` 命中 8 的倍数）。"""

    values = list(C.SPACING.values())
    assert len(values) == len(set(values)), f"间距刻度存在重复值：{values}"
    for key, value in C.SPACING.items():
        assert isinstance(value, int) and value > 0, f"{key} 非正整数：{value!r}"
    # 8px 基线兼容表述：全部是 4 的倍数，且 sm/lg/xl 命中 8 的倍数。
    assert all(value % 4 == 0 for value in values), f"存在非 4 倍数刻度：{values}"
    assert all(C.SPACING[k] % 8 == 0 for k in ("sm", "lg", "xl")), "8px 基线刻度被破坏"


def test_spacing_matches_plan_literal() -> None:
    """``SPACING`` 字典本身与计划完全一致（含非 8 倍数的 xs=4 / md=12）。"""

    assert C.SPACING == {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24}


def test_radius_matches_plan_literal() -> None:
    """``RADIUS`` 字典本身与计划**全等**（防 ``md 8→10`` 之类静默漂移）。"""

    assert C.RADIUS == {"sm": 6, "md": 8, "lg": 12, "pill": 16}


def test_font_size_matches_plan_literal() -> None:
    """``FONT_SIZE`` 字典本身与计划**全等**（防 ``display 24→99`` 之类静默漂移）。"""

    assert C.FONT_SIZE == {
        "display": 24, "title": 16, "body": 12, "caption": 11, "small": 9,
    }


def test_font_size_strictly_descending() -> None:
    """字号满足 ``display > title > body > caption > small`` **严格单调递减**。"""

    order = ("display", "title", "body", "caption", "small")
    values = [C.FONT_SIZE[k] for k in order]
    for key, value in C.FONT_SIZE.items():
        assert isinstance(value, int) and value > 0, f"{key} 非正整数：{value!r}"
    for prev_key, prev, next_key, nxt in zip(order, values, order[1:], values[1:]):
        assert prev > nxt, f"字号未严格递减：{prev_key}({prev}) > {next_key}({nxt}) 不成立"


def test_radius_values_positive_and_unique() -> None:
    """圆角刻度全为正整数且彼此不重复。"""

    values = list(C.RADIUS.values())
    assert len(values) == len(set(values)), f"圆角刻度存在重复值：{values}"
    for key, value in C.RADIUS.items():
        assert isinstance(value, int) and value > 0, f"{key} 非正整数：{value!r}"


# --------------------------------------------------------------------------- #
# 6. COLORS 键集合未被本阶段改动（全等断言由 test_color_palette_matches_prd 负责）
# --------------------------------------------------------------------------- #
def test_colors_key_set_unchanged_by_p0() -> None:
    """本阶段只做加法：``COLORS`` 键集合与 P0 前的既有 32 键一一对应。"""

    expected_keys = {
        "ink", "blush", "white", "mouse_body", "mouse_hi",
        "bubble_bg", "bubble_text", "glow_yellow", "glow_blue", "warm_brown",
        "bubble_sub_text", "bubble_faint_text", "vocab_bg", "vocab_text", "vocab_level_tag",
        "bubble_gradient_hi", "jp_button_primary_bg", "jp_button_primary_text",
        "jp_button_primary_hover", "jp_button_primary_pressed",
        "jp_button_secondary_border", "jp_button_secondary_text",
        "jp_button_secondary_hover", "jp_button_bar_bg",
        "log_status_mastered", "log_status_vocab", "log_status_unprocessed",
        "bubble_shadow", "bubble_divider", "bubble_gradient_bottom",
        "jp_level_chip_bg", "jp_level_chip_text",
        # 气泡双层描边（贴纸风）
        "bubble_border", "bubble_halo",
    }
    assert set(C.COLORS) == expected_keys


# --------------------------------------------------------------------------- #
# 7. 新 token 已同步进 __all__（项目红线）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", ["SEMANTIC_COLORS", "SPACING", "FONT_SIZE", "RADIUS"])
def test_design_tokens_exported_in_all(name: str) -> None:
    """新增常量必须同步进 ``__all__``。"""

    assert name in C.__all__
