"""ui 渲染层包标记。

本层允许 import ``PySide6.QtCore/QtGui/QtWidgets`` 与 ``desktop_pet.core.*``；
**不得 import desktop_pet.app.***（依赖方向单向：app → ui → core）。
"""

from __future__ import annotations
