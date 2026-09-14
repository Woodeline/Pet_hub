"""core.paths —— 随包资源（内置词库 JSON）的路径解析。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

用途：在**源码运行**与 **PyInstaller 冻结运行**两种环境下都能定位到内置词库文件，
且始终返回「意图路径」——即使文件尚不存在也不抛异常（由调用方 :class:`WordBank.load`
做存在性与容错判定）。
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)


def is_frozen() -> bool:
    """返回当前是否运行在 PyInstaller 冻结环境中。

    判定依据：``sys.frozen`` 为真且存在 ``sys._MEIPASS``（PyInstaller 解包目录）。
    """

    return bool(getattr(sys, "frozen", False)) and hasattr(sys, "_MEIPASS")


def package_data_dir() -> Path:
    """返回随包数据目录（``.../desktop_pet/data``）。

    - 冻结环境：``Path(sys._MEIPASS) / "desktop_pet" / "data"``
      （与 ``desktop-pet.spec`` 的 ``datas`` 落点一致）。
    - 源码环境：``<repo>/src/desktop_pet/data``
      （``__file__`` = ``.../desktop_pet/core/paths.py``，取其 ``parent.parent``）。
    """

    if is_frozen():
        meipass = getattr(sys, "_MEIPASS")
        return Path(meipass) / "desktop_pet" / C.WORD_BANK_DIR_NAME
    return Path(__file__).resolve().parent.parent / C.WORD_BANK_DIR_NAME


def word_bank_path() -> Path:
    """返回内置 JLPT 词库 JSON 的意图路径（始终返回，不因文件缺失而抛）。"""

    return package_data_dir() / C.WORD_BANK_FILE_NAME


__all__ = ["is_frozen", "package_data_dir", "word_bank_path"]
