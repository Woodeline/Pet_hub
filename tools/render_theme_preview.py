"""tools/render_theme_preview.py —— 主题离屏预览（dev 工具，**零新依赖**）。

用途：把 :class:`desktop_pet.ui.pet_renderer.PetRenderer` 的渲染结果按当前 ``THEMES``
离屏渲染成 PNG，供人工**肉眼比对**配色层级的演进（阶段 B1 降饱和前后）。

**硬约束**：输出目录必须指向**仓库外**（本仓零外部图片素材，PNG 一律不得入库）；
工具脚本本身可提交到 ``tools/``。

用法（在仓库根、已装依赖的 Python 环境下）：

    QT_QPA_PLATFORM=offscreen python tools/render_theme_preview.py \\
        --stage b1-before \\
        --outdir "C:/Users/王佐成/WorkBuddy/软件开发/_ui-review-phase-b"

可选参数：

    --scale 0.8   渲染缩放（默认 0.8）

退出码：``0`` = 全部写出；``2`` = 参数或渲染错误。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# 必须在导入 PySide6 之前设置离屏后端（无显示环境也能渲染）。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSize, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop_pet.core import constants as C  # noqa: E402
from desktop_pet.core.constants import Expression  # noqa: E402
from desktop_pet.core.pet_model import PetModel, PetPose  # noqa: E402
from desktop_pet.ui.pet_renderer import PetRenderer  # noqa: E402

#: 与 ``constants.THEMES`` 的键顺序一致（固定顺序便于逐张比对）。
THEMES = (
    "default", "spring", "summer", "autumn", "winter",
    "spring_festival", "christmas",
)


def render_pose(renderer: PetRenderer, pose: PetPose, scale: float, path: Path) -> Path:
    """把一帧姿态渲染为 PNG 并写出，返回路径。"""

    width = int(round(C.BASE_W * scale))
    height = int(round(C.BASE_H * scale))
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        renderer.paint(painter, pose, scale, QSize(width, height))
    finally:
        painter.end()
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"PNG 写出失败：{path}")
    return path


def theme_series(
    renderer: PetRenderer, outdir: Path, stage: str, scale: float
) -> list[Path]:
    """7 套皮肤各渲染一帧（清醒基础态）。"""

    pose = PetModel.pose_for_expression(Expression.HAPPY)
    written: list[Path] = []
    for name in THEMES:
        renderer.set_theme(name)
        written.append(render_pose(renderer, pose, scale, outdir / f"{stage}-{name}.png"))
    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="desktop-pet 主题离屏预览")
    parser.add_argument("--outdir", required=True, help="输出目录（建议在仓库外）")
    parser.add_argument("--stage", required=True, help="文件名前缀，如 b1-before / b1-desat5")
    parser.add_argument("--scale", type=float, default=0.8, help="渲染缩放（默认 0.8）")
    args = parser.parse_args(argv)

    outdir = Path(args.outdir).expanduser()
    if not outdir.is_absolute():
        parser.error("--outdir 必须是绝对路径（且指向仓库外）")
    outdir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    renderer = PetRenderer()
    written = theme_series(renderer, outdir, args.stage, args.scale)
    for path in written:
        print(str(path))
    del app  # 显式持有到结束，避免过早回收
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
