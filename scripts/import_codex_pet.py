#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Codex Pet v2 的 spritesheet 导入成本项目的皮肤包。

Codex Pet v2 图集规范（1536×2288，11 行 × 8 列，单元格 192×208）是画师
**逐帧**做的动画——头发飘动、尾巴摆动、眨眼都在帧里，不是对单张图做形变。
本脚本按行切出所需动作，转成 ``skins/<包名>/{pet_conf,act_conf}.json +
action/<前缀>_<N>.png``，从而走项目现有的帧图渲染通道。

两处必须处理的差异：

1. **行有固定语义**（idle / waving / jumping / failed …），且每行只用前 N 格；
   空尾格必须丢掉，否则尾部会冒出"空白帧"。
2. **本项目的 act_conf 只有单一 ``frame_refresh``，而 Codex 每帧时长不等**
   （idle 是 280/110/110/140/140/320ms）。因此按最短帧长取基准，把慢帧
   **复制成多份**，用等长帧模拟原始节奏——帧图数量多一点，但格式保持最简。

用法：
    python scripts/import_codex_pet.py --sheet /tmp/sheet_b.webp --name deepseek_whale
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QRect
from PySide6.QtGui import QColor, QImage, QPainter

REPO = Path(__file__).resolve().parents[1]
SKINS_DIR = REPO / "skins"

CELL_W, CELL_H = 192, 208
SHEET_W, SHEET_H = 1536, 2288
ALPHA_CUT = 8

#: 每格最短可见内容像素数（低于此值视为空尾格）。
MIN_CELL_PIXELS = 100


@dataclass(frozen=True)
class Row:
    """图集里的一行动作。"""

    index: int
    frames: int
    durations_ms: tuple[int, ...]


#: Codex Pet v2 固定行表（行号 → 状态 → 帧数 → 各帧时长）。
ROWS: dict[str, Row] = {
    "idle": Row(0, 6, (280, 110, 110, 140, 140, 320)),
    "running-right": Row(1, 8, (120, 220, 120, 220, 120, 220, 120, 220)),
    "running-left": Row(2, 8, (120, 220, 120, 220, 120, 220, 120, 220)),
    "waving": Row(3, 4, (140, 280, 140, 280)),
    "jumping": Row(4, 5, (140, 280, 140, 280, 140)),
    "failed": Row(5, 8, (140, 240, 140, 240, 140, 240, 140, 240)),
    "waiting": Row(6, 6, (150, 260, 150, 260, 150, 260)),
    "running": Row(7, 6, (120, 220, 120, 220, 120, 220)),
    "review": Row(8, 6, (150, 280, 150, 280, 150, 280)),
    "look-up": Row(9, 8, (140,) * 8),
    "look-down": Row(10, 8, (140,) * 8),
}


@dataclass(frozen=True)
class SlotPlan:
    """一个皮肤包动作 = 图集里的一行 + 本项目的槽位映射。"""

    action: str        # act_conf 里的动作名
    row: str           # 图集行名
    prefix: str        # 帧图文件名前缀
    slots: tuple[str, ...] = ()


#: 只导入渲染器真的会播的槽位（其余行导进来也不会被预载，纯占磁盘）。
#: 拖拽用 ``failed``：被拎起来慌张的样子比"挥手"更贴切。
#: 左右跑动行对应 ``left`` / ``right``：窗口空闲游走滑行时按朝向选槽位。
DEFAULT_PLAN: tuple[SlotPlan, ...] = (
    SlotPlan("idle", "idle", "whale_idle", ("default", "focus", "on_floor")),
    SlotPlan("waving", "waving", "whale_wave", ("patpat",)),
    SlotPlan("failed", "failed", "whale_drag", ("drag",)),
    SlotPlan("jumping", "jumping", "whale_jump", ("fall", "prefall")),
    SlotPlan("running-right", "running-right", "whale_run_right", ("right",)),
    SlotPlan("running-left", "running-left", "whale_run_left", ("left",)),
)


# --------------------------------------------------------------------------- #
# 图像
# --------------------------------------------------------------------------- #
def load_sheet(path: Path) -> QImage:
    image = QImage(str(path))
    if image.isNull():
        raise SystemExit(f"图集无法解码（可能下载被截断）：{path}")
    if image.width() != SHEET_W or image.height() != SHEET_H:
        raise SystemExit(
            f"图集尺寸 {image.width()}×{image.height()} 不符合 Codex v2 规范 "
            f"{SHEET_W}×{SHEET_H}"
        )
    return image.convertToFormat(QImage.Format.Format_ARGB32)


def opaque_bbox(image: QImage) -> QRect:
    """不透明像素包围盒（扫 constBits，整图约 10ms）。"""

    w, h = image.width(), image.height()
    stride = image.bytesPerLine()
    pixels = memoryview(image.constBits()).cast("B")
    min_x, min_y, max_x, max_y = w, h, -1, -1
    for y in range(h):
        row = pixels[y * stride:(y + 1) * stride]
        for x in range(w):
            if row[x * 4 + 3] > ALPHA_CUT:
                if x < min_x:
                    min_x = x
                if x > max_x:
                    max_x = x
                if y < min_y:
                    min_y = y
                if y > max_y:
                    max_y = y
    if max_x < 0:
        return QRect()
    return QRect(min_x, min_y, max_x - min_x + 1, max_y - min_y + 1)


def opaque_count(image: QImage) -> int:
    stride = image.bytesPerLine()
    pixels = memoryview(image.constBits()).cast("B")
    total = 0
    for y in range(image.height()):
        row = pixels[y * stride:(y + 1) * stride]
        for x in range(image.width()):
            if row[x * 4 + 3] > ALPHA_CUT:
                total += 1
    return total


# --------------------------------------------------------------------------- #
# 切帧
# --------------------------------------------------------------------------- #
def slice_row(sheet: QImage, row: Row) -> list[QImage]:
    """切出一行的有效帧（自动去掉尾部空格，并校验内容非空）。"""

    cells: list[QImage] = []
    for col in range(row.frames):
        cell = sheet.copy(col * CELL_W, row.index * CELL_H, CELL_W, CELL_H)
        if opaque_count(cell) < MIN_CELL_PIXELS:
            break
        cells.append(cell)
    if not cells:
        raise SystemExit(f"行 {row.index} 切不出任何有效帧")
    return cells


def duplicate_by_timing(cells: list[QImage], durations: tuple[int, ...]
                        ) -> tuple[list[QImage], float]:
    """按各帧时长复制慢帧，返回 (等长帧序列, 单帧秒数)。

    本项目 act_conf 只有单一 ``frame_refresh``，所以以最短帧长为基准，
    把 2 倍、3 倍时长的帧各复制成多份——用帧数换回原来的节奏感。
    """

    base = min(durations[:len(cells)])
    out: list[QImage] = []
    for cell, dur in zip(cells, durations):
        out.extend([cell] * max(1, round(dur / base)))
    return out, base / 1000.0


# --------------------------------------------------------------------------- #
# 落盘
# --------------------------------------------------------------------------- #
def write_pack(sheet: QImage, plan: tuple[SlotPlan, ...], name: str,
               credits: str, merge: bool = False) -> dict[str, object]:
    pack_dir = SKINS_DIR / name
    action_dir = pack_dir / "action"
    pet_path = pack_dir / "pet_conf.json"
    act_path = pack_dir / "act_conf.json"

    existing_pet: dict[str, object] = {}
    existing_act: dict[str, object] = {}
    if merge:
        if not (pet_path.is_file() and act_path.is_file()):
            raise SystemExit(f"--merge 需要已存在的皮肤包：{pack_dir}")
        existing_pet = json.loads(pet_path.read_text(encoding="utf-8"))
        existing_act = json.loads(act_path.read_text(encoding="utf-8"))
        print(f"合并进已存在的皮肤包：{pack_dir}（已有动作 {sorted(existing_act)}）")
    elif pack_dir.exists():
        print(f"覆盖已存在的皮肤包：{pack_dir}")
    action_dir.mkdir(parents=True, exist_ok=True)

    # 先切出全部动作的原始帧，量一次公共并集，保证所有动作用同一画布。
    sliced: dict[str, tuple[list[QImage], float]] = {}
    union = QRect()
    for item in plan:
        row = ROWS[item.row]
        cells = slice_row(sheet, row)
        frames, refresh = duplicate_by_timing(cells, row.durations_ms)
        for frame in cells:  # 用未复制的原始帧算包围盒，重复帧不改变几何
            box = opaque_bbox(frame)
            union = union.united(box) if not union.isEmpty() else box
        sliced[item.action] = (frames, refresh)
        print(f"  {item.action:13s} ← 行{row.index:<2d} {item.row:13s} "
              f"{len(cells)} 帧 → {len(frames)} 帧 @ {refresh:.2f}s"
              f"{'（空尾格已截断）' if len(cells) < row.frames else ''}")

    if union.isEmpty():
        raise SystemExit("所有帧都是空的，图集可能不是有效素材")

    if merge:
        # 追加动作必须与现有画布完全一致，否则新帧与旧帧会错位。
        if (union.width(), union.height()) != (
            existing_pet.get("width"), existing_pet.get("height")
        ):
            raise SystemExit(
                f"追加动作需要 {union.width()}×{union.height()} 画布，"
                f"现有包是 {existing_pet.get('width')}×{existing_pet.get('height')}；"
                "两者不一致会导致新旧帧错位，已中止"
            )

    act_conf: dict[str, object] = dict(existing_act) if merge else {}
    written = 0
    skipped: list[str] = []
    for item in plan:
        if merge and item.action in existing_act:
            skipped.append(item.action)
            continue
        frames, refresh = sliced[item.action]
        act_conf[item.action] = {
            "images": item.prefix,
            "act_num": 1,
            "frame_refresh": round(refresh, 3),
            "anchor": [0, 0],
        }
        for i, frame in enumerate(frames):
            frame.copy(union).save(
                str(action_dir / f"{item.prefix}_{i}.png"), "PNG"
            )
            written += 1

    pet_conf: dict[str, object] = dict(existing_pet) if merge else {
        "width": union.width(),
        "height": union.height(),
        "scale": 1.0,
        "meta": {
            "name": name,
            "author": "YunYueSama",
            "version": "1.0",
            "credits": credits,
        },
    }
    slot_map: dict[str, str] = {
        k: str(v) for k, v in pet_conf.items()
        if k not in {"width", "height", "scale", "meta"}
    }
    for item in plan:
        for slot in item.slots:
            # 合并模式不覆盖已有映射（旧包的调校以磁盘现状为准）。
            slot_map.setdefault(slot, item.action)
    for slot, action in slot_map.items():
        pet_conf[slot] = action

    pet_path.write_text(
        json.dumps(pet_conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    act_path.write_text(
        json.dumps(act_conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"frames": written, "skipped": skipped,
            "canvas": (union.width(), union.height()),
            "union": union, "slots": slot_map}


def preview(sheet: QImage, plan: tuple[SlotPlan, ...], out: Path,
            canvas: QRect) -> None:
    """把导入的动作帧按画布并排拼成检查图（每动作一行）。"""

    rows = [sliced_frames for sliced_frames in
            (duplicate_by_timing(slice_row(sheet, ROWS[i.row]), ROWS[i.row].durations_ms)[0]
             for i in plan)]
    longest = max(len(r) for r in rows)
    sheet_out = QImage(longest * (canvas.width() + 6) + 6,
                       len(rows) * (canvas.height() + 6) + 6,
                       QImage.Format.Format_ARGB32)
    sheet_out.fill(QColor(245, 245, 245, 255))
    painter = QPainter(sheet_out)
    try:
        for r, frames in enumerate(rows):
            for c, frame in enumerate(frames):
                painter.drawImage(6 + c * (canvas.width() + 6),
                                  6 + r * (canvas.height() + 6),
                                  frame.copy(canvas))
    finally:
        painter.end()
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet_out.save(str(out), "PNG")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sheet", required=True, help="Codex v2 spritesheet（webp/png）")
    ap.add_argument("--name", required=True, help="皮肤包目录名")
    ap.add_argument("--credits", default=(
        "作者：YunYueSama · 仓库：https://github.com/YunYueSama/codex-deepseek-pet · "
        "许可：大肥鱼项目署名许可 1.0（须保留作者与仓库地址，修改需注明）。"
        "角色设计源自社区二创，底层角色权属以原权利人为准。"
    ))
    ap.add_argument("--preview", default="")
    ap.add_argument("--merge", action="store_true",
                    help="只追加包内尚不存在的动作，已有动作与调校保持原样")
    args = ap.parse_args()

    sheet = load_sheet(Path(args.sheet))
    print(f"图集 {sheet.width()}×{sheet.height()} ✓ Codex Pet v2")
    summary = write_pack(sheet, DEFAULT_PLAN, args.name, args.credits, args.merge)
    print(f"画布 {summary['canvas'][0]}×{summary['canvas'][1]}，"
          f"新写 {summary['frames']} 帧 → {SKINS_DIR / args.name}")
    if summary["skipped"]:
        print(f"跳过已有动作：{'、'.join(summary['skipped'])}")
    print(f"槽位映射：{summary['slots']}")

    if args.preview:
        # 必须用真实并集矩形：有原点偏移，QRect(0,0,w,h) 会整体错位。
        preview(sheet, DEFAULT_PLAN, Path(args.preview), summary["union"])
        print(f"检查图：{args.preview}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
