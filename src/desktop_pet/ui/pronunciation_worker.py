"""ui.pronunciation_worker —— 把 ``core.tts_client`` + ``core.audio_cache`` 的同步
抓取/落盘放到 ``QThreadPool`` 后台线程。

线程边界（与 ``word_detail_worker`` 同范式）：
- ``core.tts_client`` / ``core.audio_cache`` 纯同步（**不开线程、不 import Qt/time**）。
- ``QThreadPool`` / ``QRunnable`` / ``QObject`` 信号只出现在 ``ui`` 层。
- ``PronunciationSignals`` 在主线程创建；``succeeded/failed`` 跨线程经
  ``QueuedConnection`` 回主线程。
- ``run()`` 内**绝不裸抛**：``TTSError`` 与兜底 ``Exception`` 一律转 ``failed`` 信号。
- 键（``key``）= 发音文本（``spoken_text`` 结果），信号携带它供主线程定位词条。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from desktop_pet.core.audio_cache import AudioCacheStore
from desktop_pet.core.tts_client import TTSClient, TTSError, spoken_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TTSNetConfig:
    """发音联网配置快照（与 ``WordDetailNetConfig`` 同思路：现取现构）。"""

    timeout_s: float = 6.0


class PronunciationSignals(QObject):
    """发音抓取的回传信号（跨线程）。"""

    succeeded = Signal(str, object)  # (key, Path)
    failed = Signal(str, str)        # (key, error_message)


class PronunciationWorker(QRunnable):
    """在后台线程完成「查缓存 → 未命中联网抓取 → 落盘」一次发音获取。"""

    def __init__(
        self,
        key: str,
        word: str,
        kana: str,
        cache: AudioCacheStore,
        net: TTSNetConfig,
    ) -> None:
        """构造抓取任务。

        Args:
            key: 发音文本（缓存键与信号定位符）。
            word: 词头表记（抓取优先用）。
            kana: 假名读音（表记为空时兜底）。
            cache: 音频缓存存储（后台线程内读写磁盘）。
            net: 联网配置。
        """

        super().__init__()
        self.key: str = str(key)
        self.word: str = str(word or "")
        self.kana: str = str(kana or "")
        self.cache: AudioCacheStore = cache
        self.net: TTSNetConfig = net
        self.signals: PronunciationSignals = PronunciationSignals()

    def run(self) -> None:
        """执行抓取并转 ``succeeded`` / ``failed`` 信号（绝不裸抛）。"""

        try:
            cached = self.cache.load(self.key)
            if cached is not None:
                self.signals.succeeded.emit(self.key, cached)
                return
            client = TTSClient(timeout_s=self.net.timeout_s)
            data = client.fetch(self.word, self.kana)
            path = self.cache.save(self.key, data)
            if path is None:
                # 落盘失败（只读盘等）：退化为系统临时文件，本次仍可播放
                #（不入缓存，下次点击重新联网）。
                path = self._write_temp(data)
            self.signals.succeeded.emit(self.key, path)
        except TTSError as exc:
            logger.info("发音获取失败（%s）：%s", self.key, exc)
            self.signals.failed.emit(self.key, str(exc))
        except Exception as exc:  # noqa: BLE001 —— 后台线程边界处绝不裸抛
            logger.exception("发音获取未预期异常（%s）", self.key)
            self.signals.failed.emit(self.key, str(exc))

    @staticmethod
    def _write_temp(data: bytes) -> Path:
        """把音频字节落到系统临时目录（供本次播放；失败则抛给兜底分支）。"""

        import tempfile

        fd, tmp_name = tempfile.mkstemp(suffix=".mp3")
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        return Path(tmp_name)


__all__ = ["TTSNetConfig", "PronunciationSignals", "PronunciationWorker", "spoken_text"]
