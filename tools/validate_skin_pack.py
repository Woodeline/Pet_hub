# -*- coding: utf-8 -*-
"""皮肤包自检工具（社区作者用）。

对指定目录执行与程序加载时**完全相同**的校验（core.skin_pack.load_skin_pack），
打印全部致命问题 / 警告与包摘要。校验未通过时退出码为 1，便于脚本化集成。

用法：
    python tools/validate_skin_pack.py <皮肤包目录>

示例：
    python tools/validate_skin_pack.py skins/MyCat
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 命令行工具：直接以仓库根/src 为导入根（不依赖安装）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from desktop_pet.core.skin_pack import SkinPackError, load_skin_pack  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="皮肤包自检：与程序加载同一套校验（致命问题 / 警告 / 包摘要）"
    )
    parser.add_argument("pack_root", help="皮肤包目录（内含 pet_conf.json / act_conf.json / action/）")
    args = parser.parse_args(argv)

    root = Path(args.pack_root)
    try:
        pack = load_skin_pack(root)
    except SkinPackError as exc:
        print("✗ 校验未通过：")
        for issue in exc.issues:
            print(f"  [问题] {issue}")
        return 1

    print(f"✓ 校验通过：{root.name}")
    if pack.warnings:
        print("警告（不致命，建议修复）：")
        for warning in pack.warnings:
            print(f"  [警告] {warning}")
    total_frames = sum(len(action.expanded_frames) for action in pack.actions.values())
    mapped = "、".join(f"{slot}→{name}" for slot, name in sorted(pack.action_map.items()))
    print(f"画布：{pack.width}×{pack.height} · scale {pack.scale:g}")
    print(f"动作：{len(pack.actions)} 个 · 展开后帧共 {total_frames} 张")
    print(f"槽位映射：{mapped}")
    meta = pack.meta
    if meta.name or meta.author or meta.version:
        print(f"元数据：{meta.name or root.name}" + (f" · 作者 {meta.author}" if meta.author else "") + (f" · 版本 {meta.version}" if meta.version else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
