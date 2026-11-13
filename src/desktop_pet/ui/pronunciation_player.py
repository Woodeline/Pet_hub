"""ui.pronunciation_player —— 发音 MP3 播放封装（主线程，跨平台）。

平台实现：

- **Windows**：系统自带 ``winmm`` 的 MCI 接口（标准库 ``ctypes``，零新增依赖）。
  ``mciSendStringW``：``open "<mp3>" type mpegvideo alias <a>`` + ``play <a>``；
  ``type mpegvideo`` 打不开时回落按文件关联打开。
- **macOS**：系统自带 ``afplay``（``subprocess`` 零新增依赖）。异步播放 +
  主线程 ``QTimer`` 轮询退出码；``stop()`` = ``terminate()`` 打断上一次播放。
- 其他平台：无可用系统播放器，``play`` 时统一报「不可用」。

- 单实例串行播放：多词连点不叠加出声（Windows 先 ``close`` 上一个别名；
  macOS 先 ``terminate`` 上一个进程）。
- 同步错误码（Windows）／非零退出码（macOS）：open / play 任一失败 →
  :attr:`play_failed` 上报，由
  :class:`~desktop_pet.ui.speaker_button.PronunciationController` 删缓存 + 置错误态。
- 本模块**只在主线程使用**；单测不构造本类（往 controller 注入 fake player）。
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

logger = logging.getLogger(__name__)

try:  # 非 Windows / 缺 winmm 时保持可导入（play 时统一报「不可用」）
    import ctypes

    _winmm = ctypes.WinDLL("winmm")  # noqa: E305 —— 环境探测放模块顶部
except (AttributeError, OSError):  # pragma: no cover —— 仅非 Windows 触发
    _winmm = None

_MCI_OK: int = 0

#: macOS ``afplay`` 退出码轮询间隔（ms）
_POLL_INTERVAL_MS: int = 200


def _mci(command: str) -> int:
    """发送一条 MCI 命令字符串，返回错误码（0 = 成功）。"""

    if _winmm is None:
        return 1
    return int(_winmm.mciSendStringW(command, None, 0, None))


class PronunciationPlayer(QObject):
    """封装一次 ``play(path)`` / ``stop()`` 的最小播放器。"""

    #: (key, error_message) —— 播放出错（含打开失败）时发出
    play_failed = Signal(str, str)

    def __init__(self, parent: QObject | None = None) -> None:
        """创建播放器（无系统资源占用；别名 / 子进程在首次播放时才分配）。"""

        super().__init__(parent)
        self._alias: str = ""
        self._current_key: str = ""
        self._seq: int = 0
        # macOS：afplay 子进程 + 退出码轮询定时器
        self._proc: subprocess.Popen | None = None
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(_POLL_INTERVAL_MS)
        self._poll_timer.timeout.connect(self._on_poll_timeout)

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def play(self, key: str, path: Path) -> None:
        """播放 ``path`` 指向的音频（自动打断上一次播放）。"""

        self.stop()
        self._current_key = str(key)
        self._seq += 1
        if sys.platform == "darwin":
            self._play_darwin(path)
            return
        self._play_mci(path)

    def stop(self) -> None:
        """停止并释放当前播放（无播放也安全）。"""

        self._stop_darwin()
        if self._alias:
            _mci(f"close {self._alias}")
            self._alias = ""

    # ------------------------------------------------------------------ #
    # Windows：winmm / MCI
    # ------------------------------------------------------------------ #
    def _play_mci(self, path: Path) -> None:
        """Windows MCI 播放路径（打不开 / 播失败 → ``play_failed``）。"""

        if _winmm is None:
            self.play_failed.emit(self._current_key, "当前系统不支持音频播放")
            return
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

    # ------------------------------------------------------------------ #
    # macOS：afplay 子进程 + 退出码轮询
    # ------------------------------------------------------------------ #
    def _play_darwin(self, path: Path) -> None:
        """macOS ``afplay`` 播放路径（启动失败 / 非零退出 → ``play_failed``）。"""

        try:
            self._proc = subprocess.Popen(
                ["afplay", str(path)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            self._proc = None
            self.play_failed.emit(self._current_key, "音频播放启动失败")
            return
        self._poll_timer.start()

    def _stop_darwin(self) -> None:
        """结束 macOS 播放：停轮询 + 终止子进程（无进程也安全）。"""

        self._poll_timer.stop()
        proc = self._proc
        if proc is not None:
            try:
                proc.terminate()
                proc.wait(timeout=1.0)
            except (OSError, subprocess.TimeoutExpired):
                try:
                    proc.kill()
                except OSError:
                    pass
            self._proc = None

    def _on_poll_timeout(self) -> None:
        """轮询 ``afplay`` 退出码：非零 → 上报播放失败。"""

        proc = self._proc
        if proc is None:
            self._poll_timer.stop()
            return
        returncode = proc.poll()
        if returncode is None:
            return
        self._proc = None
        self._poll_timer.stop()
        if returncode != 0:
            self.play_failed.emit(self._current_key, "音频播放失败")

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    @property
    def current_key(self) -> str:
        """最近一次请求播放的发音键（供诊断）。"""

        return self._current_key


__all__ = ["PronunciationPlayer"]
