# -*- coding: utf-8 -*-
"""复现:喇叭 tooltip 黑块。

场景 A:SpeakerButton 带 setStyleSheet("background: transparent;")(现状)
场景 B:同样窗口,但按钮不带该样式(对照组)
各自强制 QToolTip.showText,grab tooltip 顶层窗口,统计像素。
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication
from PySide6.QtWidgets import QApplication, QLabel, QVBoxLayout, QWidget

from desktop_pet.ui import theme
from desktop_pet.ui.speaker_button import SpeakerButton


def tooltip_top_level():
    for w in QApplication.topLevelWidgets():
        if w.windowType() == Qt.WindowType.ToolTip and w.isVisible():
            return w
    return None


def analyze(img):
    dark = light = transparent = 0
    n = img.width() * img.height()
    for x in range(img.width()):
        for y in range(img.height()):
            c = QColor.fromRgba(img.pixel(x, y))
            a = c.alpha()
            v = (c.red() + c.green() + c.blue()) / 3
            if a < 32:
                transparent += 1
            elif v < 40:
                dark += 1
            elif v > 180:
                light += 1
    return dark, light, transparent, n


def run_case(with_button_qss: bool, out_png: str):
    app = QApplication.instance() or QApplication([])
    win = QWidget()
    theme.apply_theme(win)
    lay = QVBoxLayout(win)
    word = QLabel("テスト")
    lay.addWidget(word)
    btn = SpeakerButton(win)
    if not with_button_qss:
        btn.setStyleSheet("")  # 对照组:去掉按钮自带的透明背景样式
    lay.addWidget(btn)
    win.resize(300, 200)
    win.show()
    app.processEvents()

    # 预热 tooltip 生命链,再强制显示
    btn.setToolTip("点击播放发音")
    from PySide6.QtWidgets import QToolTip
    QToolTip.showText(btn.mapToGlobal(btn.rect().center()), "点击播放发音", btn)
    for _ in range(30):
        app.processEvents()

    tip = tooltip_top_level()
    if tip is None:
        print(f"[case with_button_qss={with_button_qss}] tooltip 未出现")
        return
    img = tip.grab().toImage()
    img.save(out_png)
    dark, light, transparent, n = analyze(img)
    print(f"[case with_button_qss={with_button_qss}] size={img.width()}x{img.height()} "
          f"dark={dark}/{n} ({dark * 100.0 / n:.1f}%) light={light}/{n} ({light * 100.0 / n:.1f}%) "
          f"transparent={transparent}/{n} ({transparent * 100.0 / n:.1f}%)")
    QToolTip.hideText()
    win.hide()
    for _ in range(10):
        app.processEvents()


if __name__ == "__main__":
    # 截图只进系统临时目录：仓库内留 PNG 会触发 test_icon_factory 的资产守卫
    import tempfile
    out_dir = tempfile.mkdtemp(prefix="tooltip_repro_")
    run_case(True, os.path.join(out_dir, "tooltip_case_A_with_btn_qss.png"))
    run_case(False, os.path.join(out_dir, "tooltip_case_B_no_btn_qss.png"))
    print("done ->", out_dir)
