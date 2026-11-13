#!/bin/bash
# ============================================================
#  desktop-pet launcher (macOS)
#  双击（访达中"打开"）或在终端执行本脚本即可启动。
#  启动优先级：打包版 dist/desktop-pet.app → 项目 .venv → 系统 Python
# ============================================================

cd "$(dirname "$0")" || exit 1
APPDIR="$(pwd)"

# src-layout：把 src 加入 PYTHONPATH
export PYTHONPATH="$APPDIR/src${PYTHONPATH:+:$PYTHONPATH}"

# --- 1) 优先打包版 .app（无需 Python） ---
if [ -x "$APPDIR/dist/desktop-pet.app/Contents/MacOS/desktop-pet" ]; then
    exec open "$APPDIR/dist/desktop-pet.app"
fi

# --- 2) 项目本地 venv ---
if [ -x "$APPDIR/.venv/bin/python" ]; then
    exec "$APPDIR/.venv/bin/python" -m desktop_pet.main
fi

# --- 3) 兜底：系统自带 python3（需已安装 PySide6 + pynput） ---
if command -v python3 >/dev/null 2>&1; then
    exec python3 -m desktop_pet.main
fi

# --- 4) 兜底：WorkBuddy 自带运行时 ---
FB="$HOME/.workbuddy/binaries/python/envs/default/bin/python"
if [ -x "$FB" ]; then
    exec "$FB" -m desktop_pet.main
fi

echo
echo "  [ERROR] 未找到可用的 Python 运行时。"
echo
echo "  方式 A: 直接运行打包版 dist/desktop-pet.app"
echo "  方式 B: 安装 Python 3.13，然后按 README.md 执行："
echo "      python3 -m venv .venv"
echo "      .venv/bin/pip install -r requirements.txt"
echo
exit 1
