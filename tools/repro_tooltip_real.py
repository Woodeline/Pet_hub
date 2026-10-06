# -*- coding: utf-8 -*-
"""真实 Windows 平台复现:喇叭 tooltip 渲染。

非 offscreen(用原生 windows 平台),编程触发 tooltip 后抓屏裁剪 tooltip 区域,
输出到系统临时目录,人工查看是否黑块。截图不留仓库(资产守卫)。
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from desktop_pet.ui import theme
from desktop_pet.ui.speaker_button import SpeakerButton


def tooltip_top_level():
    for w in QApplication.topLevelWidgets():
        if w.metaObject().className() == "QTipLabel" and w.isVisible():
            return w
    return None


def main():
    app = QApplication([])
    win = QWidget()
    theme.apply_theme(win)
    lay = QVBoxLayout(win)
    lay.addWidget(QLabel("テスト"))
    btn = SpeakerButton(win)
    lay.addWidget(btn)
    win.move(100, 100)
    win.show()

    def show_tip():
        QToolTip.showText(btn.mapToGlobal(btn.rect().center()), "点击播放发音", btn)
        print("after showText, visible:", QToolTip.isVisible())
        tops = [w.metaObject().className() for w in QApplication.topLevelWidgets()]
        print("top-levels:", tops)

    def grab():
        tip = tooltip_top_level()
        print("grab time, visible:", QToolTip.isVisible())
        if tip is None:
            print("tooltip 未出现")
            app.quit()
            return
        screen = app.primaryScreen()
        full = screen.grabWindow(0)  # 全屏
        geo = tip.frameGeometry()
        crop = full.copy(geo)
        out = os.path.join(tempfile.mkdtemp(prefix="tooltip_real_"), "tooltip_real.png")
        crop.save(out)
        print("tooltip geometry:", geo)
        print("saved:", out)
        app.quit()

    QTimer.singleShot(500, show_tip)
    QTimer.singleShot(2000, grab)
    app.exec()


if __name__ == "__main__":
    main()
