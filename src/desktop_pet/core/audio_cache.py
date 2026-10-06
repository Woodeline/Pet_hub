"""core.audio_cache —— 发音 MP3 用户级磁盘缓存（sha1 命名 + 原子写）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``。**

设计要点（沿用本项目 store 范式）：
- 缓存为**单文件一词条**的目录形态（``audio_cache/<sha1(text)>.mp3``），
  不是 JSON 索引——音频是二进制且无元数据需求，文件系统即索引。
- 键 = 发音文本（:func:`desktop_pet.core.tts_client.spoken_text` 的结果），
  ``sha1`` 散列避免非法文件名字符与超长文件名。
- 写 = ``tempfile.mkstemp`` 同目录 + ``flush/fsync`` + ``os.replace`` 原子替换
  （与 :class:`~desktop_pet.core.word_details_cache_store.WordDetailsCacheStore` 同式）。
- 读 = 仅做「存在 + 非空」判定，不做内容校验；损坏文件在**播放失败**时由
  调用方 :meth:`discard` 删除后重取（播放层才知道文件是否真的能放）。
"""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from pathlib import Path

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)

_AUDIO_EXT: str = ".mp3"
#: 空文件（或只有 0 字节占位）视为未命中。
_MIN_FILE_BYTES: int = 1


class AudioCacheStore:
    """负责发音 MP3 缓存目录的按词读取、原子写入与删除。"""

    def __init__(self, directory: Path) -> None:
        """创建音频缓存存储。

        Args:
            directory: 缓存目录绝对路径（不必已存在，首次写入时创建）。
        """

        self._dir: Path = Path(directory)

    # ------------------------------------------------------------------ #
    # 路径
    # ------------------------------------------------------------------ #
    @property
    def directory(self) -> Path:
        """缓存目录路径。"""

        return self._dir

    @staticmethod
    def default_path() -> Path:
        """返回默认缓存目录 ``%APPDATA%\\desktop-pet\\audio_cache``。

        ``APPDATA`` 不可用时回落到用户主目录，保证任何环境下都返回一个可写路径。
        """

        from desktop_pet.core.paths import audio_cache_dir

        return audio_cache_dir()

    # ------------------------------------------------------------------ #
    # 键
    # ------------------------------------------------------------------ #
    @staticmethod
    def _key(text: str) -> str:
        """发音文本 → 缓存文件名（不含目录）。"""

        digest = hashlib.sha1(str(text).encode("utf-8")).hexdigest()
        return digest + _AUDIO_EXT

    def path_for(self, text: str) -> Path:
        """返回 ``text`` 对应的缓存文件意图路径（不因文件缺失而抛）。"""

        return self._dir / self._key(text)

    # ------------------------------------------------------------------ #
    # 读
    # ------------------------------------------------------------------ #
    def load(self, text: str) -> Path | None:
        """查询缓存：命中且非空返回文件路径，未命中返回 ``None``。

        任何 IO 异常（权限等）一律视为未命中，绝不抛出。
        """

        path = self.path_for(text)
        try:
            if path.is_file() and path.stat().st_size >= _MIN_FILE_BYTES:
                return path
        except OSError as exc:
            logger.debug("音频缓存读取异常（%s）：%s", text, exc)
        return None

    # ------------------------------------------------------------------ #
    # 写
    # ------------------------------------------------------------------ #
    def save(self, text: str, data: bytes) -> Path | None:
        """原子写入一条音频缓存，返回落盘路径；失败记录日志并返回 ``None``。

        - 目录不存在则递归创建；创建失败返回 ``None``（发音仍可当次播放，
          只是下次需重新联网）。
        - ``data`` 为空视为非法输入，直接拒绝。
        """

        if not data:
            logger.debug("音频缓存拒绝写入空数据（%s）", text)
            return None
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            path = self.path_for(text)
            fd, tmp_name = tempfile.mkstemp(dir=str(self._dir), suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(tmp_name, path)
            except BaseException:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
            return path
        except OSError as exc:
            logger.warning("音频缓存写入失败（%s）：%s", text, exc)
            return None

    # ------------------------------------------------------------------ #
    # 删
    # ------------------------------------------------------------------ #
    def discard(self, text: str) -> None:
        """删除一条缓存（不存在则静默）；用于播放失败后清掉损坏文件。"""

        path = self.path_for(text)
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            logger.debug("音频缓存删除失败（%s）：%s", text, exc)


__all__ = ["AudioCacheStore"]
