"""主题皮肤渐变表回归测试（阶段 A1）。

守护 ``core.constants`` 的新增主题表：

- ``THEMES`` 恰含 7 套皮肤；每套恰好 5 个停靠点，位置严格 ``0.0/0.25/0.5/0.75/1.0``。
- 每套色值均合法 ``#RRGGBB``（大写）。
- ``default`` 与 ``BODY_GRADIENT_STOPS`` **同一对象**（``is``），保证阶段 B 降饱和自动跟随。
- 7 套皮肤的停靠点序列**两两不同**。
- ``THEME_SEASON_MAP`` 覆盖 1..12 全部月份、值都在 ``THEMES`` 内。
- ``THEME_ALLOWED`` = 7 套皮肤 + ``auto``，成员数恰为 **8**。

期望值一律写成**字面量**，不用被测常量拼期望（防自引用假绿，项目红线）。
"""

from __future__ import annotations

import re

import pytest

from desktop_pet.core import constants as C

_HEX_RE = re.compile(r"^#[0-9A-F]{6}$")

#: 期望的 7 套皮肤键（字面量，防“少一套/多一套”静默漂移）。
_EXPECTED_THEMES = {
    "default", "spring", "summer", "autumn", "winter",
    "spring_festival", "christmas",
}
#: 期望的停靠点位置序列（字面量）。
_EXPECTED_POSITIONS = (0.0, 0.25, 0.5, 0.75, 1.0)


# --------------------------------------------------------------------------- #
# 1. 皮肤集合与结构
# --------------------------------------------------------------------------- #
def test_themes_key_set_matches_plan() -> None:
    """``THEMES`` 恰含 7 套皮肤（键集合字面量全等）。"""

    assert set(C.THEMES) == _EXPECTED_THEMES
    assert len(C.THEMES) == 7


@pytest.mark.parametrize("name", sorted(_EXPECTED_THEMES))
def test_each_theme_has_five_stops(name: str) -> None:
    """每套皮肤恰好 5 个停靠点。"""

    assert len(C.THEMES[name]) == 5, f"{name} 停靠点数 != 5"


@pytest.mark.parametrize("name", sorted(_EXPECTED_THEMES))
def test_each_theme_positions_strictly_increasing(name: str) -> None:
    """位置严格 ``0.0/0.25/0.5/0.75/1.0``（首个 0.0、末个 1.0，严格单调）。"""

    positions = tuple(pos for pos, _hexv in C.THEMES[name])
    assert positions == _EXPECTED_POSITIONS, f"{name} 停靠点位置不符：{positions}"


@pytest.mark.parametrize("name", sorted(_EXPECTED_THEMES))
def test_each_theme_colors_are_valid_uppercase_hex(name: str) -> None:
    """色值一律合法的**大写** ``#RRGGBB``。"""

    for pos, hexv in C.THEMES[name]:
        assert isinstance(hexv, str), f"{name}@{pos} 非字符串：{hexv!r}"
        assert _HEX_RE.match(hexv), f"{name}@{pos} 非法色值（须大写 #RRGGBB）：{hexv!r}"
        int(hexv[1:], 16)  # 必须可解析


# --------------------------------------------------------------------------- #
# 2. default 与 BODY_GRADIENT_STOPS 是同一对象
# --------------------------------------------------------------------------- #
def test_default_theme_is_body_gradient_stops_object() -> None:
    """``default`` 直接引用 ``BODY_GRADIENT_STOPS`` 对象本身（``is``，非复制）。"""

    assert C.THEMES["default"] is C.BODY_GRADIENT_STOPS


def test_default_theme_name_and_auto_constants() -> None:
    """``DEFAULT_THEME`` / ``AUTO_THEME`` 字面量。"""

    assert C.DEFAULT_THEME == "default"
    assert C.AUTO_THEME == "auto"


# --------------------------------------------------------------------------- #
# 3. 7 套皮肤停靠点序列两两不同
# --------------------------------------------------------------------------- #
def test_all_theme_stop_sequences_are_pairwise_distinct() -> None:
    """7 套皮肤的完整停靠点序列**两两不同**（否则换肤视觉无差异）。"""

    sequences = {name: C.THEMES[name] for name in _EXPECTED_THEMES}
    names = sorted(_EXPECTED_THEMES)
    duplicates: list[tuple[str, str]] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if sequences[a] == sequences[b]:
                duplicates.append((a, b))
    assert not duplicates, f"存在停靠点序列完全相同的皮肤对：{duplicates}"


def test_all_theme_color_sets_are_pairwise_distinct() -> None:
    """进一步：即便忽略位置，7 套皮肤用到的**色值集合**也两两不同。"""

    color_sets = {name: frozenset(h for _p, h in C.THEMES[name]) for name in _EXPECTED_THEMES}
    names = sorted(_EXPECTED_THEMES)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert color_sets[a] != color_sets[b], f"{a} 与 {b} 色值集合相同"


# --------------------------------------------------------------------------- #
# 4. 季节映射
# --------------------------------------------------------------------------- #
def test_season_map_covers_all_twelve_months() -> None:
    """``THEME_SEASON_MAP`` 覆盖 1..12 全部月份。"""

    assert set(C.THEME_SEASON_MAP) == set(range(1, 13))


def test_season_map_values_are_valid_themes() -> None:
    """季节映射的值都指向 ``THEMES`` 内的皮肤，且**仅**四季（不含节日皮肤）。"""

    values = set(C.THEME_SEASON_MAP.values())
    assert values <= set(C.THEMES)
    assert values == {"spring", "summer", "autumn", "winter"}


@pytest.mark.parametrize(
    "month,expected",
    [
        (1, "winter"), (2, "winter"), (3, "spring"), (4, "spring"),
        (5, "spring"), (6, "summer"), (7, "summer"), (8, "summer"),
        (9, "autumn"), (10, "autumn"), (11, "autumn"), (12, "winter"),
    ],
)
def test_season_map_literal_expectations(month: int, expected: str) -> None:
    """逐月字面量期望（四季映射精确到月）。"""

    assert C.THEME_SEASON_MAP[month] == expected


# --------------------------------------------------------------------------- #
# 5. 白名单
# --------------------------------------------------------------------------- #
def test_theme_allowed_has_eight_members() -> None:
    """``THEME_ALLOWED`` = 7 套皮肤 + ``auto``，成员数恰为 8（字面量）。"""

    assert len(C.THEME_ALLOWED) == 8
    assert C.THEME_ALLOWED == _EXPECTED_THEMES | {"auto"}


def test_theme_names_cover_themes_and_auto() -> None:
    """显示名覆盖 7 套皮肤 + ``auto``（中文非空）。"""

    assert set(C.THEME_NAMES) == _EXPECTED_THEMES | {"auto"}
    assert all(value.strip() for value in C.THEME_NAMES.values())


# --------------------------------------------------------------------------- #
# 6. __all__ 同步（项目红线）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "name",
    [
        "THEMES", "DEFAULT_THEME", "AUTO_THEME",
        "THEME_NAMES", "THEME_SEASON_MAP", "THEME_ALLOWED",
        "TRAY_MENU_THEME", "THEME_RECHECK_MS",
    ],
)
def test_theme_constants_exported_in_all(name: str) -> None:
    """新增主题常量必须同步进 ``__all__``。"""

    assert name in C.__all__
