"""tools/render_theme_preview.py —— 主题离屏预览（dev 工具，**零新依赖**）。

用途：把 :class:`desktop_pet.ui.pet_renderer.PetRenderer` 的渲染结果按当前 ``THEMES``
离屏渲染成 PNG，供人工**肉眼比对**配色层级的演进（阶段 B1 降饱和前后）与微交互 /
换姿态（阶段 B2 / C1）。

**硬约束**：输出目录必须指向**仓库外**（本仓零外部图片素材，PNG 一律不得入库）；
工具脚本本身可提交到 ``tools/``。

用法（在仓库根、已装依赖的 Python 环境下）：

    QT_QPA_PLATFORM=offscreen python tools/render_theme_preview.py \\
        --stage b1-before \\
        --outdir "C:/Users/王佐成/WorkBuddy/软件开发/_ui-review-phase-b"

    # 阶段 B2 微交互三帧（悬停凝视 / 点击过冲 / 气泡打字感）
    QT_QPA_PLATFORM=offscreen python tools/render_theme_preview.py \\
        --stage b2 --outdir "C:/Users/王佐成/WorkBuddy/软件开发/_ui-review-phase-b"

    # 阶段 C1：气泡打字中途 + 终态，以及换姿态（趴着 / 侧卧）
    QT_QPA_PLATFORM=offscreen python tools/render_theme_preview.py \\
        --stage c1 --outdir "C:/Users/王佐成/WorkBuddy/软件开发/_ui-review-phase-c"

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

from PySide6.QtCore import QPoint, QSize, Qt  # noqa: E402
from PySide6.QtGui import (  # noqa: E402
    QFont,
    QFontDatabase,
    QFontInfo,
    QImage,
    QPainter,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from desktop_pet.core import constants as C  # noqa: E402
from desktop_pet.core.constants import Expression  # noqa: E402
from desktop_pet.core.pet_model import PetModel, PetPose, SurpriseKind  # noqa: E402
from desktop_pet.core.vocabulary import VocabEntry  # noqa: E402
from desktop_pet.ui.bubble import BubbleWindow  # noqa: E402
from desktop_pet.ui.pet_renderer import PetRenderer  # noqa: E402

#: 与 ``constants.THEMES`` 的键顺序一致（固定顺序便于逐张比对）。
THEMES = (
    "default", "spring", "summer", "autumn", "winter",
    "spring_festival",
)

#: 阶段 B2 微交互预览的入口 stage 名。
MICRO_STAGE = "b2"
#: 阶段 C1（空闲游走 / 换姿态）预览的入口 stage 名。
IDLE_STAGE = "c1"

#: 预览用词条规定内容（固定，便于逐张比对）。
_PREVIEW_WORD = VocabEntry(
    id="n5-0001", level="N5", word="食べる", kana="たべる",
    translation="吃", meaning="进食", romaji="taberu",
)

#: 常见的 Windows 中文字体文件（按优先级）：应用字体族取不到时的兜底注册来源。
_FALLBACK_FONT_FILES = (
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/msyh.ttf",
    "C:/Windows/Fonts/msyhbd.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    "C:/Windows/Fonts/simsun.ttc",
)


def ensure_cjk_font() -> str:
    """确保离屏渲染能取到中文字体族，并把诊断信息打到 stdout。

    复用**应用真实字体路径**（``constants.JP_BUBBLE_FONT_FAMILY``，与
    ``ui.bubble`` 构造 ``QFont`` 所用族一致）：先查 ``QFontDatabase.families()``
    是否已含该族；不含则尝试从 Windows 字体文件 ``addApplicationFont`` 注册；仍不含
    则返回该族名并打印明确提示（属**已知离屏限制**，**不改应用源码**，接受可读性降级）。

    Returns:
        期望使用的字体族名（= ``C.JP_BUBBLE_FONT_FAMILY``）。
    """

    wanted = C.JP_BUBBLE_FONT_FAMILY
    families = QFontDatabase.families()
    has_wanted = wanted in families
    print(f"[font] 目标族 = {wanted!r}")
    print(f"[font] QFontDatabase 已有族数 = {len(families)}")
    print(f"[font] 系统是否直接含目标族 = {has_wanted}")

    if not has_wanted:
        for candidate in _FALLBACK_FONT_FILES:
            if not os.path.exists(candidate):
                continue
            font_id = QFontDatabase.addApplicationFont(candidate)
            names = (
                QFontDatabase.applicationFontFamilies(font_id) if font_id >= 0 else []
            )
            print(f"[font] 注册 {candidate} -> id={font_id} families={names}")
            if wanted in names or wanted in QFontDatabase.families():
                has_wanted = True
                break

    resolved = QFontInfo(QFont(wanted)).family()
    print(f"[font] QFont({wanted!r}) 实际解析族 = {resolved!r}")
    if not has_wanted:
        print(
            "[font] 警告：离屏环境未取到目标字体族，中文可能显示为方块/豆腐块"
            "（已知离屏限制，不改应用源码，接受可读性降级）"
        )
    return wanted


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


def render_bubble(path: Path, reveal: float) -> Path:
    """把学习泡泡渲染为 PNG（``reveal`` = 打字进度 ``0…1``；``1.0`` 为终态）。"""

    bubble = BubbleWindow()
    bubble.set_anchor(QPoint(0, 0))
    bubble.show_word(_PREVIEW_WORD, 30.0)
    bubble._alpha = 1.0
    bubble._reveal = reveal
    image = QImage(bubble.size(), QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    try:
        bubble.render(painter, QPoint(0, 0))
    finally:
        painter.end()
    bubble.hide_bubble()
    if not image.save(str(path), "PNG"):
        raise RuntimeError(f"PNG 写出失败：{path}")
    return path


def micro_series(renderer: PetRenderer, outdir: Path, scale: float) -> list[Path]:
    """阶段 B2 微交互三帧：悬停凝视 / 点击过冲 / 气泡打字感。"""

    renderer.set_theme(C.DEFAULT_THEME)
    written: list[Path] = []

    # ① 悬停凝视：看向右侧偏上的光标（look_x > 0 / look_y < 0）
    gaze_model = PetModel()
    gaze_model.set_hover(True)
    gaze_model.set_gaze(1.0, -0.4)
    now = 0.0
    for _ in range(40):
        now += 0.02
        gaze_model.update(0.02, now)
    written.append(
        render_pose(renderer, gaze_model.pose(), scale, outdir / "b2-hover-gaze.png")
    )

    # ② 点击过冲：把弹跳包络钉在峰值附近（progress≈0.3 → u≈0.6）再收敛渲染
    click_model = PetModel()
    now = 0.0
    for _ in range(60):
        click_model._click_timer = C.CLICK_ANIM_S * 0.7
        now += 0.02
        click_model.update(0.02, now)
    written.append(
        render_pose(renderer, click_model.pose(), scale, outdir / "b2-click-overshoot.png")
    )

    # ③ 气泡打字感：单词行 reveal≈0.45 的中途帧
    written.append(render_bubble(outdir / "b2-bubble-typing.png", 0.45))
    return written


def posture_pose(renderer: PetRenderer, kind: SurpriseKind, scale: float, path: Path) -> Path:
    """渲染一个「换姿态」（LOAF / LIE_SIDE）的保持段帧为 PNG。

    把 ``_surprise_elapsed`` 每轮钉在 ``POSTURE_DURATION_S`` 的保持段（包络 = 1.0），
    让姿态稳定收敛到「增量全量叠加」的状态，而非上升 / 回弹中途。
    """

    model = PetModel()
    model.set_base_expression(Expression.HAPPY)
    model.set_expression(Expression.HAPPY, 0.0)
    hold = C.POSTURE_DURATION_S * 0.45  # 包络保持段（[0.3d, 0.6d)）→ = 1.0
    now = 0.0
    for _ in range(60):
        model._surprise_kind = kind
        model._surprise_elapsed = hold
        now += 0.02
        model.update(0.02, now)
    return render_pose(renderer, model.pose(), scale, path)


def idle_series(renderer: PetRenderer, outdir: Path, scale: float) -> list[Path]:
    """阶段 C1 四帧：气泡打字中途 + 气泡终态 + 趴着 + 侧卧。"""

    renderer.set_theme(C.DEFAULT_THEME)
    written: list[Path] = []
    written.append(render_bubble(outdir / "c1-bubble-typing.png", 0.45))
    written.append(render_bubble(outdir / "c1-bubble-final.png", 1.0))
    written.append(
        posture_pose(renderer, SurpriseKind.LOAF, scale, outdir / "c1-posture-loaf.png")
    )
    written.append(
        posture_pose(renderer, SurpriseKind.LIE_SIDE, scale, outdir / "c1-posture-lie-side.png")
    )
    return written


def theme_series(
    renderer: PetRenderer, outdir: Path, stage: str, scale: float
) -> list[Path]:
    """6 套皮肤各渲染一帧（清醒基础态）。"""

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
    parser.add_argument(
        "--decor-phase", type=float, default=0.0,
        help="装饰动画相位（秒）；粒子位置是该相位的纯函数（阶段 D 证据用）",
    )
    args = parser.parse_args(argv)

    outdir = Path(args.outdir).expanduser()
    if not outdir.is_absolute():
        parser.error("--outdir 必须是绝对路径（且指向仓库外）")
    outdir.mkdir(parents=True, exist_ok=True)

    app = QApplication.instance() or QApplication(sys.argv[:1])
    # 字体就绪：离屏下先确保中文字体族可用（打印诊断），再渲染任何含中文的帧。
    ensure_cjk_font()
    renderer = PetRenderer()
    renderer.set_decor_phase(args.decor_phase)
    if args.stage == MICRO_STAGE:
        written = micro_series(renderer, outdir, args.scale)
    elif args.stage == IDLE_STAGE:
        written = idle_series(renderer, outdir, args.scale)
    else:
        written = theme_series(renderer, outdir, args.stage, args.scale)
    for path in written:
        print(str(path))
    del app  # 显式持有到结束，避免过早回收
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
