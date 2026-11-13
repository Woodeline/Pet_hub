#!/usr/bin/env python3
"""scripts/build_macos_app.py —— 打包 macOS ``.app`` bundle（源码运行模式）。

产物：``dist/desktop-pet.app`` —— 双击即可启动，无需终端、无需解压。
bundle 内的可执行文件是一个 shell 启动器，按优先级挑选 Python 运行时：
项目 ``.venv`` → 系统 ``python3`` → WorkBuddy 自带运行时。

同时程序化生成 App 图标（复用 ``core.constants`` 的渐变色 token，零外部图片素材），
经 ``iconutil`` 编译为 ``AppIcon.icns``。

用法::

    python3 scripts/build_macos_app.py [--project-root PATH] [--no-icon]

注意：本脚本与 Windows 侧 ``desktop-pet.spec``（PyInstaller）互相独立——
macOS 侧刻意保持"源码 + venv"运行模式，避免 PyInstaller 冻结带来的
PySide6 体积膨胀与 macOS 签名 / 公证复杂度。
"""

from __future__ import annotations

import argparse
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

#: bundle 标识（与 constants 的 AUTOSTART_LAUNCH_AGENT_LABEL 无冲突：bundle id 仅用于 macOS）
BUNDLE_ID = "com.desktop-pet.app"
BUNDLE_NAME = "desktop-pet"
DISPLAY_NAME = "小喵酱"

#: iconset 规格（basename, 像素尺寸）——iconutil 要求的命名约定
_ICONSET_SPEC = (
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
)


def project_version(project_root: Path) -> str:
    """从 ``pyproject.toml`` 读取版本号（解析失败回落 0.0.0）。"""

    pyproject = project_root / "pyproject.toml"
    try:
        for line in pyproject.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("version"):
                # version = "0.6.3"
                return stripped.split("=", 1)[1].strip().strip('"').strip("'")
    except OSError:
        pass
    return "0.0.0"


def write_info_plist(bundle_dir: Path, version: str) -> None:
    """写入 ``Contents/Info.plist``（plistlib 序列化）。"""

    payload = {
        "CFBundleName": BUNDLE_NAME,
        "CFBundleDisplayName": DISPLAY_NAME,
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": version,
        "CFBundleShortVersionString": version,
        "CFBundleExecutable": BUNDLE_NAME,
        "CFBundlePackageType": "APPL",
        "CFBundleIconFile": "AppIcon.icns",
        "CFBundleInfoDictionaryVersion": "6.0",
        # 最小系统版本：PySide6 6.8 要求 macOS 11+
        "LSMinimumSystemVersion": "11.0",
        # 无 Dock 图标的"代理应用"（桌宠常驻托盘，与 Windows"不占任务栏"对齐）
        "LSUIElement": True,
        "NSHighResolutionCapable": True,
        "NSSupportsAutomaticGraphicsSwitching": True,
    }
    plist_path = bundle_dir / "Contents" / "Info.plist"
    with plist_path.open("wb") as handle:
        plistlib.dump(payload, handle)


def write_launcher(bundle_dir: Path, project_root: Path) -> None:
    """写入 ``Contents/MacOS/desktop-pet`` 启动器（bash，运行时挑选 Python）。"""

    launcher = bundle_dir / "Contents" / "MacOS" / BUNDLE_NAME
    launcher.parent.mkdir(parents=True, exist_ok=True)
    # 运行时**相对定位优先**（Contents/MacOS 上溯四级 = 项目根，bundle 可整体
    # 迁移）；构建时烙入的绝对路径仅作相对定位失败时的兜底。
    # （缺陷修复：原实现烙入路径优先、相对回退少算一层——项目目录一旦移动，
    #   bundle 启动即 ModuleNotFoundError 且无任何可见提示。）
    launcher.write_text(
        f"""#!/bin/bash
# desktop-pet.app 启动器（由 scripts/build_macos_app.py 生成，请勿手改）
BAKED_ROOT="{project_root}"
SELF="$0"
while [ -h "$SELF" ]; do
    LS="$(ls -ld "$SELF")"
    SELF="${{LS#* -> }}"
done
HERE="$(cd "$(dirname "$SELF")" && pwd)"
CANDIDATE="$(cd "$HERE/../../../.." 2>/dev/null && pwd)"
if [ -f "$CANDIDATE/src/desktop_pet/main.py" ]; then
    PROJECT_ROOT="$CANDIDATE"
else
    PROJECT_ROOT="$BAKED_ROOT"
fi

export PYTHONPATH="$PROJECT_ROOT/src${{PYTHONPATH:+:$PYTHONPATH}}"

pick_python() {{
    if [ -x "$PROJECT_ROOT/.venv/bin/python" ]; then
        echo "$PROJECT_ROOT/.venv/bin/python"
        return 0
    fi
    if command -v python3 >/dev/null 2>&1; then
        if python3 -c "import PySide6" >/dev/null 2>&1; then
            echo "$(command -v python3)"
            return 0
        fi
    fi
    if [ -x "$HOME/.workbuddy/binaries/python/envs/default/bin/python" ]; then
        echo "$HOME/.workbuddy/binaries/python/envs/default/bin/python"
        return 0
    fi
    return 1
}}

PY="$(pick_python)" || {{
    osascript -e 'display dialog "未找到可用的 Python 运行时。\\n请先在项目目录执行 .venv/bin/pip install -r requirements.txt" buttons {{"好"}} default button "好" with title "desktop-pet" with icon stop' >/dev/null 2>&1
    exit 1
}}

exec "$PY" -m desktop_pet.main
""",
        encoding="utf-8",
    )
    launcher.chmod(0o755)


def render_icon_pngs(iconset_dir: Path, project_root: Path) -> bool:
    """用 PySide6 offscreen 程序化渲染图标 PNG（失败返回 False，不阻断打包）。"""

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, str(project_root / "src"))
        from PySide6.QtCore import QPointF, QRectF, Qt
        from PySide6.QtGui import QBrush, QColor, QGuiApplication, QLinearGradient, QPainter, QPen, QPixmap

        from desktop_pet.core import constants as C
    except Exception as exc:  # noqa: BLE001 —— 图标缺失不应阻断 bundle 生成
        print(f"[warn] 图标渲染跳过（依赖不可用）: {exc}")
        return False

    app = QGuiApplication(sys.argv[:1])
    try:
        for filename, pixel in _ICONSET_SPEC:
            pixmap = QPixmap(pixel, pixel)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            try:
                _paint_icon(painter, pixel, C.BODY_GRADIENT_STOPS, C.COLORS)
            finally:
                painter.end()
            if not pixmap.save(str(iconset_dir / filename), "PNG"):
                print(f"[warn] 图标 PNG 写出失败: {filename}")
                return False
    finally:
        app.quit()
    return True


def _paint_icon(painter: "QPainter", size: int, stops, colors: dict) -> None:
    """在方形画布上画：渐变圆角底 + 白色团子猫脸（与宠物矢量渲染同源配色）。"""

    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QBrush, QColor, QLinearGradient, QPen, QPolygonF

    # —— 渐变圆角底 ——
    gradient = QLinearGradient(0, 0, size, size)
    for pos, hexv in stops:
        gradient.setColorAt(pos, QColor(hexv))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(gradient))
    radius = size * 0.225
    painter.drawRoundedRect(QRectF(0, 0, size, size), radius, radius)

    ink = QColor(colors.get("ink", "#141414"))
    white = QColor("#FFFFFF")
    blush = QColor(colors.get("blush", "#FFB3C7"))

    # —— 耳朵（两个圆角三角） ——
    ear_w = size * 0.20
    ear_h = size * 0.22
    cx = size * 0.5
    head_r = size * 0.30
    head_cy = size * 0.56
    for sign in (-1.0, 1.0):
        base_x = cx + sign * head_r * 0.62
        base_y = head_cy - head_r * 0.72
        polygon = QPolygonF(
            [
                QPointF(base_x - ear_w / 2, base_y + ear_h * 0.35),
                QPointF(base_x + sign * ear_w * 0.55, base_y - ear_h * 0.75),
                QPointF(base_x + ear_w / 2, base_y + ear_h * 0.35),
            ]
        )
        painter.setBrush(QBrush(white))
        painter.setPen(QPen(ink, max(1.0, size * 0.018)))
        painter.drawPolygon(polygon)

    # —— 脸（白色圆） ——
    painter.setPen(QPen(ink, max(1.0, size * 0.018)))
    painter.setBrush(QBrush(white))
    painter.drawEllipse(QRectF(cx - head_r, head_cy - head_r, head_r * 2, head_r * 2))

    # —— 眼睛（两个椭圆） ——
    eye_r = size * 0.045
    eye_dx = size * 0.105
    eye_dy = size * 0.045
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QBrush(ink))
    for sign in (-1.0, 1.0):
        painter.drawEllipse(
            QRectF(cx + sign * eye_dx - eye_r, head_cy - eye_dy - eye_r, eye_r * 2, eye_r * 2)
        )

    # —— 腮红 ——
    blush_r = size * 0.035
    blush_dx = size * 0.185
    blush_dy = size * 0.075
    painter.setBrush(QBrush(blush))
    for sign in (-1.0, 1.0):
        painter.drawEllipse(
            QRectF(
                cx + sign * blush_dx - blush_r,
                head_cy + blush_dy - blush_r,
                blush_r * 2,
                blush_r * 2,
            )
        )

    # —— 嘴（小 "w"：两段弧线） ——
    mouth_w = size * 0.05
    mouth_dy = size * 0.115
    painter.setPen(QPen(ink, max(1.0, size * 0.016)))
    painter.setBrush(Qt.BrushStyle.NoBrush)
    for sign in (-1.0, 1.0):
        painter.drawArc(
            QRectF(
                cx + sign * mouth_w / 2 - mouth_w / 2,
                head_cy + mouth_dy - mouth_w / 2,
                mouth_w,
                mouth_w,
            ),
            200 * 16,
            140 * 16,
        )


def build_icns(iconset_dir: Path, icns_path: Path) -> bool:
    """调 ``iconutil`` 把 iconset 编译为 icns（工具缺失时返回 False）。"""

    iconutil = shutil.which("iconutil")
    if iconutil is None:
        print("[warn] 未找到 iconutil（Xcode 命令行工具），跳过 .icns 编译")
        return False
    result = subprocess.run(
        [iconutil, "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[warn] iconutil 编译失败: {result.stderr.strip()}")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="打包 desktop-pet macOS .app bundle")
    parser.add_argument("--project-root", type=Path, default=None, help="项目根目录（默认取脚本上两级）")
    parser.add_argument("--no-icon", action="store_true", help="跳过图标生成")
    args = parser.parse_args()

    project_root = (args.project_root or Path(__file__).resolve().parent.parent).resolve()
    if not (project_root / "src" / "desktop_pet" / "main.py").exists():
        print(f"[error] 项目根目录无效（未找到 src/desktop_pet/main.py）: {project_root}")
        return 1

    version = project_version(project_root)
    dist_dir = project_root / "dist"
    bundle_dir = dist_dir / f"{BUNDLE_NAME}.app"

    if bundle_dir.exists():
        shutil.rmtree(bundle_dir)
    (bundle_dir / "Contents" / "MacOS").mkdir(parents=True)
    (bundle_dir / "Contents" / "Resources").mkdir(parents=True)

    write_info_plist(bundle_dir, version)
    write_launcher(bundle_dir, project_root)

    icon_ok = False
    if not args.no_icon:
        iconset_dir = bundle_dir / "Contents" / "Resources" / "AppIcon.iconset"
        iconset_dir.mkdir(parents=True, exist_ok=True)
        icon_ok = render_icon_pngs(iconset_dir, project_root)
        if icon_ok:
            icon_ok = build_icns(iconset_dir, bundle_dir / "Contents" / "Resources" / "AppIcon.icns")
        if iconset_dir.exists():
            shutil.rmtree(iconset_dir)
    if not icon_ok and not args.no_icon:
        # 无图标时从 Info.plist 摘掉 CFBundleIconFile，避免系统找不到图标报错
        plist_path = bundle_dir / "Contents" / "Info.plist"
        with plist_path.open("rb") as handle:
            payload = plistlib.load(handle)
        payload.pop("CFBundleIconFile", None)
        with plist_path.open("wb") as handle:
            plistlib.dump(payload, handle)

    print(f"[ok] 已生成 {bundle_dir}")
    print(f"     版本 v{version}（源码运行模式，启动器自动挑选 Python 运行时）")
    if icon_ok:
        print("     AppIcon.icns 已生成")
    print("     双击 .app 或执行 open dist/desktop-pet.app 启动")
    print("     提示：开机自启请在托盘菜单勾选（写入 ~/Library/LaunchAgents/desktop-pet.plist）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
