"""core.theme —— 主题皮肤的**纯逻辑**解析（零 Qt / 零 time）。

主题常量表（``THEMES`` / ``THEME_SEASON_MAP`` / ``THEME_ALLOWED`` …）留在
:mod:`desktop_pet.core.constants`；本模块只承载「按用户选择 + 月份解析出生效皮肤」与
「取停靠点」两类**纯函数**，符合「constants 只放阈值/配色/尺寸/文案」的约定。

``AUTO_THEME`` 需要「当前月份」，但 **core 层禁止 import time**（架构红线）——月份一律由
app 层注入（启动时 + 每日重估定时器），本模块因此保持纯函数、可确定性测试。
"""

from __future__ import annotations

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


__all__ = ["resolve_theme", "theme_stops"]
