"""ui.pronunciation_player —— 发音 MP3 播放封装（主线程，Windows winmm/MCI）。

**为何不用 QtMultimedia**：运行环境只装 ``PySide6-Essentials``（QtMultimedia 属
Addons 轮子），引入它需新增依赖且 PyInstaller onefile 体积膨胀约几十 MB；本项目为
Windows 专用应用，故用系统自带 ``winmm`` 的 MCI 接口（标准库 ``ctypes``，零新增依赖）。

- ``mciSendStringW``：``open "<mp3>" type mpegvideo alias <a>`` + ``play <a>``；
  ``type mpegvideo`` 打不开时回落按文件关联打开。
- 单实例串行播放：``play`` 先 ``close`` 上一个别名（停止并释放），多词连点不叠加出声。
- 同步错误码：``open`` / ``play`` 任一返回非 0 → :attr:`play_failed` 上报，由
  :class:`~desktop_pet.ui.speaker_button.PronunciationController` 删缓存 + 置错误态。
- 本模块**只在主线程使用**；单测不构造本类（往 controller 注入 fake player）。
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal

logger = logging.getLogger(__name__)

try:  # 非 Windows / 缺 winmm 时保持可导入（play 时统一报「不可用」）
    import ctypes

    _winmm = ctypes.WinDLL("winmm")  # noqa: E305 —— 环境探测放模块顶部
except (AttributeError, OSError):  # pragma: no cover —— 仅非 Windows 触发
    _winmm = None

_MCI_OK: int = 0


def _mci(command: str) -> int:
    """发送一条 MCI 命令字符串，返回错误码（0 = 成功）。"""

    if _winmm is None:
        return 1
    return int(_winmm.mciSendStringW(command, None, 0, None))


class PronunciationPlayer(QObject):
    """封装一次 ``play(path)`` / ``stop()`` 的最小播放器（MCI 别名管理）。"""

    #: (key, error_message) —— 播放出错（含打开失败）时发出
    play_failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        """创建播放器（无系统资源占用；别名在首次播放时才分配）。"""

        super().__init__(parent)
        self._alias: str = ""
        self._current_key: str = ""
        self._seq: int = 0

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def play(self, key: str, path: Path) -> None:
        """播放 ``path`` 指向的音频（自动打断上一次播放）。"""

        self.stop()
        self._current_key = str(key)
        self._seq += 1
        alias = f"desktop_pet_tts_{self._seq}"
        opened = _mci(f'open "{path}" type mpegvideo alias {alias}')
        if opened != _MCI_OK:
            # 个别编解码下 mpegvideo 打不开 → 回落按文件关联（注册表 MCI 判型）。
            opened = _mci(f'open "{path}" alias {alias}')
        if opened != _MCI_OK:
            self.play_failed.emit(self._current_key, "音频设备打开失败")
            return
        if _mci(f"play {alias}") != _MCI_OK:
            _mci(f"close {alias}")
            self.play_failed.emit(self._current_key, "音频播放失败")
            return
        self._alias = alias

    def stop(self) -> None:
        """停止并释放当前播放（close 别名 = 停止 + 释放；无播放也安全）。"""

        if self._alias:
            _mci(f"close {self._alias}")
            self._alias = ""

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @property
    def current_key(self) -> str:
        """最近一次请求播放的发音键（供诊断）。"""

        return self._current_key


__all__ = ["PronunciationPlayer"]
