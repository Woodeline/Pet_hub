"""皮肤包（MOD）schema 定义与加载器。

规范全文见 ``docs/skin-pack.md``。双层配置职责边界：

- ``pet_conf.json`` **全局层（路由）**：画布尺寸、整体缩放、槽位→动作映射。
  只回答「某个状态下播放哪个动作」，不出现任何帧信息。
- ``act_conf.json`` **动作层（资源）**：每个动作的帧图前缀、循环次数、单帧
  时长、锚点修正。只回答「一个动作怎么播」，不出现路由信息。

引用方向严格单向：``pet_conf → act_conf → 帧图文件``；动作之间互不引用，
层间不得反向引用。

本模块遵守 core 红线：零 Qt / 零 time / 零 print——只做解析与校验，
不渲染、不计时（帧图显示由 ui 层后续接入）。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from desktop_pet.core import constants as C

__all__ = [
    "SkinPackError",
    "ActionSpec",
    "SkinPack",
    "load_skin_pack",
    "REQUIRED_SLOTS",
    "KNOWN_SLOTS",
    "DEFAULT_SCALE",
    "DEFAULT_ACT_NUM",
    "DEFAULT_FRAME_REFRESH_S",
]

#: pet_conf 中必须映射的槽位（最小动作集实现基线）。
REQUIRED_SLOTS: tuple[str, ...] = ("default", "drag", "fall")

#: pet_conf 中已知的全部槽位（语义对齐 DyberPet；未知键按警告容忍）。
KNOWN_SLOTS: tuple[str, ...] = (
    "default", "up", "down", "left", "right",
    "drag", "prefall", "fall", "on_floor", "patpat", "focus",
)

DEFAULT_SCALE: float = 1.0
DEFAULT_ACT_NUM: int = 1
DEFAULT_FRAME_REFRESH_S: float = 0.2
DEFAULT_ANCHOR: tuple[int, int] = (0, 0)

_PET_CONF_NAME = "pet_conf.json"
_ACT_CONF_NAME = "act_conf.json"
_ACTION_DIR_NAME = "action"


class SkinPackError(Exception):
    """皮肤包目录结构或内容非法。``issues`` 逐条列出全部问题。"""

    def __init__(self, issues: list[str]) -> None:
        self.issues: tuple[str, ...] = tuple(issues)
        super().__init__("；".join(self.issues))


@dataclass(frozen=True)
class ActionSpec:
    """单个动作定义（对应 ``act_conf.json`` 的一条）。"""

    name: str
    images: str              # 帧图前缀：action/<images>_<index>.png
    act_num: int             # 帧序列循环播放次数（≥1，帧复用机制）
    frame_refresh_s: float   # 单帧显示时长（秒，>0）
    anchor: tuple[int, int]  # 相对宠物固定位置的像素平移修正 [x, y]
    frames: tuple[str, ...]  # action/ 下实际存在的帧文件名（0..n-1 连续）

    @property
    def expanded_frames(self) -> tuple[str, ...]:
        """act_num 展开后的完整播放序列（帧循环复用，避免资源冗余）。"""

        return self.frames * self.act_num


@dataclass(frozen=True)
class SkinPack:
    """一个通过校验的皮肤包。"""

    name: str
    root: Path
    width: int
    height: int
    scale: float
    action_map: dict[str, str]       # 槽位 → 动作名（pet_conf 全局层）
    actions: dict[str, ActionSpec]   # 动作名 → 定义（act_conf 动作层）
    warnings: tuple[str, ...]

    def action_for(self, slot: str) -> ActionSpec | None:
        """返回槽位对应的动作；该槽位未映射时返回 ``None``。"""

        name = self.action_map.get(slot)
        if name is None:
            return None
        return self.actions[name]


# --------------------------------------------------------------------------- #
# 内部解析工具
# --------------------------------------------------------------------------- #
def _read_json(path: Path, issues: list[str]) -> Any:
    """读取 JSON 文件；失败时记录问题并返回 ``None``。"""

    if not path.is_file():
        issues.append(f"缺少必需文件：{path.name}")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        issues.append(f"{path.name} 不是合法 JSON：{exc}")
        return None


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_num(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _parse_canvas(pet_raw: dict[str, Any], issues: list[str]) -> tuple[int, int]:
    """解析画布尺寸；越界（超出 BASE_W/BASE_H）或非法即记问题。"""

    width = pet_raw.get("width")
    height = pet_raw.get("height")
    if not _is_int(width) or not 1 <= width <= C.BASE_W:
        issues.append(f"pet_conf.width 必须是 1~{C.BASE_W} 的整数，实际：{width!r}")
    if not _is_int(height) or not 1 <= height <= C.BASE_H:
        issues.append(f"pet_conf.height 必须是 1~{C.BASE_H} 的整数，实际：{height!r}")
    return width, height


def _parse_scale(pet_raw: dict[str, Any], issues: list[str]) -> float:
    scale = pet_raw.get("scale", DEFAULT_SCALE)
    if not _is_num(scale) or scale <= 0:
        issues.append(f"pet_conf.scale 必须是正数，实际：{scale!r}")
        return DEFAULT_SCALE
    return float(scale)


def _parse_action_map(
    pet_raw: dict[str, Any], issues: list[str], warnings: list[str]
) -> dict[str, str]:
    """提取槽位映射；未知键警告容忍，槽位值必须是非空字符串。"""

    reserved = {"width", "height", "scale"}
    for key in pet_raw:
        if key not in KNOWN_SLOTS and key not in reserved:
            warnings.append(f"pet_conf 出现未知键 {key!r}（已忽略）")

    action_map: dict[str, str] = {}
    for slot in KNOWN_SLOTS:
        if slot not in pet_raw:
            continue
        target = pet_raw[slot]
        if not isinstance(target, str) or not target.strip():
            issues.append(f"pet_conf 槽位 {slot!r} 的值必须是非空动作名，实际：{target!r}")
            continue
        action_map[slot] = target

    for slot in REQUIRED_SLOTS:
        if slot not in action_map:
            issues.append(f"pet_conf 缺少必需槽位 {slot!r}（最小动作集：default/drag/fall）")
    return action_map


def _parse_act_entry(
    name: str, raw: Any, action_dir: Path, issues: list[str], warnings: list[str]
) -> ActionSpec | None:
    """解析 act_conf.json 的一条动作定义。"""

    if not isinstance(raw, dict):
        issues.append(f"act_conf[{name!r}] 必须是对象，实际：{type(raw).__name__}")
        return None

    images = raw.get("images")
    if not isinstance(images, str) or not images.strip():
        issues.append(f"act_conf[{name!r}].images 必须是非空帧图前缀")
        return None
    if "/" in images or "\\" in images or ".." in images:
        issues.append(f"act_conf[{name!r}].images 不得包含路径分隔符：{images!r}")
        return None

    act_num = raw.get("act_num", DEFAULT_ACT_NUM)
    if not _is_int(act_num) or act_num < 1:
        issues.append(f"act_conf[{name!r}].act_num 必须是 ≥1 的整数，实际：{act_num!r}")
        return None

    frame_refresh = raw.get("frame_refresh", DEFAULT_FRAME_REFRESH_S)
    if not _is_num(frame_refresh) or frame_refresh <= 0:
        issues.append(
            f"act_conf[{name!r}].frame_refresh 必须是正数（秒），实际：{frame_refresh!r}"
        )
        return None

    anchor_raw = raw.get("anchor", list(DEFAULT_ANCHOR))
    if (
        not isinstance(anchor_raw, (list, tuple))
        or len(anchor_raw) != 2
        or not all(_is_int(v) for v in anchor_raw)
    ):
        issues.append(f"act_conf[{name!r}].anchor 必须是 [int, int]，实际：{anchor_raw!r}")
        return None

    for key in raw:
        if key not in {"images", "act_num", "frame_refresh", "anchor"}:
            warnings.append(f"act_conf[{name!r}] 出现未知键 {key!r}（已忽略）")

    # 帧图：从 0 起连续枚举 <images>_<i>.png，遇缺即停（保证 0..n-1 连续）。
    frames: list[str] = []
    index = 0
    while (action_dir / f"{images}_{index}.png").is_file():
        frames.append(f"{images}_{index}.png")
        index += 1
    if not frames:
        issues.append(
            f"act_conf[{name!r}] 在 action/ 下找不到任何帧图（前缀 {images!r}）"
        )
        return None

    # 检查是否有因断档被跳过的帧（如 0,1,2,5 → 5 被忽略）。
    extra = sorted(
        p.name
        for p in action_dir.glob(f"{images}_*.png")
        if p.name not in set(frames)
    )
    if extra:
        warnings.append(
            f"act_conf[{name!r}] 以下帧因序号不连续被忽略：{', '.join(extra)}"
        )

    return ActionSpec(
        name=name,
        images=images,
        act_num=act_num,
        frame_refresh_s=float(frame_refresh),
        anchor=(anchor_raw[0], anchor_raw[1]),
        frames=tuple(frames),
    )


# --------------------------------------------------------------------------- #
# 入口
# --------------------------------------------------------------------------- #
def load_skin_pack(root: Path) -> SkinPack:
    """加载并校验 ``root`` 处的皮肤包。

    Args:
        root: 皮肤包目录（内含 ``pet_conf.json`` / ``act_conf.json`` / ``action/``）。

    Returns:
        通过全部校验的 :class:`SkinPack`；非致命问题以 ``warnings`` 返回。

    Raises:
        SkinPackError: 目录缺失、JSON 非法、schema 违例、必需槽位/帧图缺失等。
    """

    root = Path(root)
    if not root.is_dir():
        raise SkinPackError([f"皮肤包目录不存在：{root}"])

    issues: list[str] = []
    warnings: list[str] = []

    pet_raw = _read_json(root / _PET_CONF_NAME, issues)
    act_raw = _read_json(root / _ACT_CONF_NAME, issues)
    if issues:
        raise SkinPackError(issues)

    width, height = _parse_canvas(pet_raw, issues)
    scale = _parse_scale(pet_raw, issues)
    action_map = _parse_action_map(pet_raw, issues, warnings)

    if not isinstance(act_raw, dict) or not act_raw:
        issues.append(f"{_ACT_CONF_NAME} 必须是至少含一个动作的非空对象")
        act_raw = {}

    action_dir = root / _ACTION_DIR_NAME
    actions: dict[str, ActionSpec] = {}
    for name, raw in act_raw.items():
        spec = _parse_act_entry(name, raw, action_dir, issues, warnings)
        if spec is not None:
            actions[name] = spec

    for slot, target in action_map.items():
        if target not in actions:
            issues.append(f"槽位 {slot!r} 引用的动作 {target!r} 在 act_conf 中未定义")

    if issues:
        raise SkinPackError(issues)

    return SkinPack(
        name=root.name,
        root=root,
        width=int(width),
        height=int(height),
        scale=scale,
        action_map=action_map,
        actions=actions,
        warnings=tuple(warnings),
    )
