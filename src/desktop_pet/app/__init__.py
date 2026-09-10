"""app 组装层包标记。

本层允许 import ``PySide6.QtCore`` / ``pynput`` / ``desktop_pet.ui.*`` / ``desktop_pet.core.*``，
负责跨线程桥接与系统集成（依赖方向：app → ui → core）。
"""

from __future__ import annotations
