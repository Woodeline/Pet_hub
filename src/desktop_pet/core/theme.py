"""core.theme —— 主题皮肤的**纯逻辑**解析（零 Qt / 零 time）。

主题常量表（``THEMES`` / ``THEME_SEASON_MAP`` / ``THEME_ALLOWED`` …）留在
:mod:`desktop_pet.core.constants`；本模块只承载「按用户选择 + 月份解析出生效皮肤」与
「取停靠点」两类**纯函数**，符合「constants 只放阈值/配色/尺寸/文案」的约定。

``AUTO_THEME`` 需要「当前月份」，但 **core 层禁止 import time**（架构红线）——月份一律由
app 层注入（启动时 + 每日重估定时器），本模块因此保持纯函数、可确定性测试。
"""

from __future__ import annotations

import colorsys
import math

from desktop_pet.core import constants as C


def resolve_theme(month: int, user_choice: str) -> str:
    """解析当前应生效的主题皮肤名。

    Args:
        month: 当前月份（``1..12``，由 app 层注入）。
        user_choice: 用户选择（``AUTO_THEME`` 或某套皮肤名）。

    Returns:
        - ``user_choice == AUTO_THEME`` → 按 :data:`THEME_SEASON_MAP` 映射月份；
          月份越界（非 ``1..12``）或不可解析时回落 :data:`DEFAULT_THEME`。
        - 否则原样返回 ``user_choice``（须为 :data:`THEMES` 中的皮肤名）；
          非法取值回落 :data:`DEFAULT_THEME`。
    """

    if user_choice == C.AUTO_THEME:
        try:
            month_value = int(month)
        except (TypeError, ValueError):
            return C.DEFAULT_THEME
        mapped = C.THEME_SEASON_MAP.get(month_value)
        return mapped if mapped is not None else C.DEFAULT_THEME

    if user_choice in C.THEMES:
        return user_choice
    return C.DEFAULT_THEME


def theme_stops(name: str) -> tuple[tuple[float, str], ...]:
    """取主题的渐变停靠点；未知名称回落 ``default``（防御性，**不抛异常**）。

    Args:
        name: 主题名（可为任意值；非法值回落默认皮肤）。

    Returns:
        ``(位置, ``#RRGGBB``)`` 序列；未知名称返回 ``THEMES[DEFAULT_THEME]``。
    """

    return C.THEMES.get(name, C.THEMES[C.DEFAULT_THEME])


# --------------------------------------------------------------------------- #
# 光晕派生（阶段 B1-1）—— 纯函数，零 Qt / 零 time
# --------------------------------------------------------------------------- #
#: 暖区中心色相（橙）与冷区中心色相（蓝）：用于在 5 个停靠点里挑「暖端主色 / 冷端主色」。
_WARM_HUE_DEG: float = 30.0
_COLD_HUE_DEG: float = 208.0

#: 柔光派生参数：向白提亮 + 降饱和，得到低刺激的柔光色（清醒偏暖亮、睡觉更淡）。
_AWAKE_LIGHTNESS: float = 0.82
_AWAKE_SAT: float = 0.60
_SLEEP_LIGHTNESS: float = 0.88
_SLEEP_SAT: float = 0.45

#: 向目标亮度的靠拢比例（0→1）：不直接跳到目标，保留停靠点自身明暗差异。
_LIGHT_PULL: float = 0.55


def _parse_hex(hexv: str) -> tuple[int, int, int]:
    """``#RRGGBB`` → ``(r, g, b)``（0..255）；非法输入回落中性灰（防御，不抛异常）。"""

    text = str(hexv).lstrip("#")
    if len(text) != 6:
        return (128, 128, 128)
    try:
        return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16))
    except ValueError:
        return (128, 128, 128)


def _to_hex(rgb: tuple[float, float, float]) -> str:
    """``(r, g, b)``（0..255）→ 大写 ``#RRGGBB``，分量钳制到 0..255。"""

    r, g, b = (max(0, min(255, int(round(c)))) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


def _hue_deg(hexv: str) -> float:
    """色值的色相（0..360）。"""

    r, g, b = (c / 255.0 for c in _parse_hex(hexv))
    h, _l, _s = colorsys.rgb_to_hls(r, g, b)
    return h * 360.0


def _warmth(hexv: str) -> float:
    """色温度量：``1.0`` ≈ 橙（暖端），``-1.0`` ≈ 蓝（冷端）。"""

    return math.cos(math.radians(_hue_deg(hexv) - _WARM_HUE_DEG))


def _pick_warmest(stops: tuple[tuple[float, str], ...]) -> str:
    """各停靠点里**暖端主色**（色相最接近暖区中心橙色的那个）。"""

    return max((c for _p, c in stops), key=_warmth)


def _pick_coldest(stops: tuple[tuple[float, str], ...]) -> str:
    """各停靠点里**冷端主色**（色相最接近冷区中心蓝色的那个）。"""

    return min((c for _p, c in stops), key=_warmth)


def _soften(hexv: str, *, lightness: float, sat_scale: float) -> str:
    """把主色提亮 + 降饱和成柔光色（保持色相不变）。"""

    r, g, b = (c / 255.0 for c in _parse_hex(hexv))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = l + (lightness - l) * _LIGHT_PULL
    s = s * sat_scale
    rr, gg, bb = colorsys.hls_to_rgb(h, l, s)
    return _to_hex((rr * 255.0, gg * 255.0, bb * 255.0))


def glow_for_theme(name: str, sleeping: bool) -> str:
    """按主题皮肤派生光晕色（大写 ``#RRGGBB``，纯函数 / 零 Qt / 零 time）。

    取代阶段 A3 的简版取色（那版机械取首/尾端），改为**按色相挑主色再派生**：

    * ``sleeping=False``（清醒 / 专注 / 兴奋）：取该皮肤**暖端主色**（色相最接近暖区
      中心橙色的停靠点）→ 提亮 + 降饱和成暖柔光；
    * ``sleeping=True``（睡觉）：取该皮肤**冷端主色**（色相最接近冷区中心蓝色的停靠点）
      → 更亮、更淡 → 保住「睡觉淡蓝柔光」的既有语义。

    未知皮肤回落 ``default``（经 :func:`theme_stops`，不抛异常）。

    Args:
        name: 主题名。
        sleeping: 是否睡觉态。

    Returns:
        大写字面量 ``#RRGGBB``。
    """

    stops = theme_stops(name)
    if sleeping:
        return _soften(
            _pick_coldest(stops), lightness=_SLEEP_LIGHTNESS, sat_scale=_SLEEP_SAT
        )
    return _soften(
        _pick_warmest(stops), lightness=_AWAKE_LIGHTNESS, sat_scale=_AWAKE_SAT
    )


def decor_for_theme(name: str) -> C.ThemeDecor:
    """取主题的造型装饰描述；未知名称回落 ``default``（防御性，**不抛异常**）。

    ``default`` 的装饰描述为全空（无粒子 / 无布景 / 无配件），因此**任何**非法输入
    都会安全退化成「不画装饰」，与 ``theme_stops`` 的回落策略一致。

    Args:
        name: 主题名（可为任意值）。

    Returns:
        :class:`~desktop_pet.core.constants.ThemeDecor`（不可变）。
    """

    return C.THEME_DECOR.get(name, C.THEME_DECOR[C.DEFAULT_THEME])


__all__ = ["resolve_theme", "theme_stops", "glow_for_theme", "decor_for_theme"]
