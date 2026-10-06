"""core.paths —— 随包资源（内置词库 JSON）的路径解析。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

用途：在**源码运行**与 **PyInstaller 冻结运行**两种环境下都能定位到内置词库文件，
且始终返回「意图路径」——即使文件尚不存在也不抛异常（由调用方 :class:`WordBank.load`
做存在性与容错判定）。
"""

from __future__ import annotations

import logging
import os
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


def extra_word_bank_path() -> Path:
    """返回用户导入的外置词库 JSON 意图路径（始终返回，不因文件缺失而抛）。

    位置与用户数据一致：``%APPDATA%\\desktop-pet\\jlpt_words_extra.json``
    （``APPDATA`` 不可用回落到用户主目录，与 ``VocabStore.default_path`` 同口径）。
    启动时由 :meth:`WordBank` 合并进内置词库（按 id 去重、外置覆盖）。
    """

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home()
    return base / C.CONFIG_DIR_NAME / C.EXTRA_WORD_BANK_FILE_NAME


def word_details_path() -> Path:
    """返回内置中文详情库 JSON 的意图路径（始终返回，不因文件缺失而抛）。

    文件缺失时由 :meth:`~desktop_pet.core.word_detail_bank.WordDetailBank.load`
    优雅降级为空库，不影响启动。
    """

    return package_data_dir() / C.WORD_DETAILS_FILE_NAME


def audio_cache_dir() -> Path:
    """返回发音 MP3 缓存目录意图路径（始终返回，不因目录缺失而抛）。

    位置与用户数据一致：``%APPDATA%\\desktop-pet\\audio_cache\\``
    （``APPDATA`` 不可用回落到用户主目录，与 :meth:`extra_word_bank_path` 同口径）。
    目录由 :class:`~desktop_pet.core.audio_cache.AudioCacheStore` 在首次写入时创建。
    """

    appdata = os.environ.get("APPDATA")
    base = Path(appdata) if appdata else Path.home()
    return base / C.CONFIG_DIR_NAME / C.AUDIO_CACHE_DIR_NAME


def skins_dir() -> Path:
    """返回用户自装皮肤包根目录（``skins/``，本地投放、不入库）。

    - 冻结环境：``Path(sys.executable).parent / "skins"``（exe 同目录，便于用户投放）。
    - 源码环境：``<repo>/skins``（``__file__`` 上溯三级到仓库根）。

    该目录已被 ``.gitignore`` 排除（第三方素材仅限本地自用，绝不入库），
    因此本函数**始终返回意图路径**，即使目录尚不存在也不抛异常。
    """

    if is_frozen():
        return Path(sys.executable).resolve().parent / "skins"
    return Path(__file__).resolve().parent.parent.parent.parent / "skins"


__all__ = [
    "is_frozen",
    "package_data_dir",
    "word_bank_path",
    "extra_word_bank_path",
    "word_details_path",
    "audio_cache_dir",
    "skins_dir",
]
