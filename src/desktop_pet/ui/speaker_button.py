"""ui.speaker_button —— 可点击喇叭按钮 + 发音控制器（详情窗 / 生词本卡片共用）。

组成：
- :class:`SpeakerButton`：喇叭图标按钮（QLabel 派生）。三态视觉：
  常态（主文字色）/ 获取中（置灰 + 「正在获取…」tooltip）/ 失败（置灰 + 失败提示）。
  只发 :attr:`clicked` 信号，**不含任何发音业务**。
- :class:`PronunciationController`：发音编排（QObject，主线程）。缓存命中直接播；
  未命中经 ``QThreadPool`` 后台 :class:`~desktop_pet.ui.pronunciation_worker.PronunciationWorker`
  联网抓取并落盘，再交 :class:`~desktop_pet.ui.pronunciation_player.PronunciationPlayer`
  播放。状态经 :attr:`state_changed(key, state, message)` 广播，两个窗口各自按
  ``key``（= 发音文本）过滤刷新自己的喇叭。

线程边界：controller 与窗口全部在主线程；只有 worker 的磁盘/网络在后台线程。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QSize, QThreadPool, Qt, Signal
from PySide6.QtWidgets import QLabel, QWidget

from desktop_pet.core import constants as C
from desktop_pet.core.audio_cache import AudioCacheStore
from desktop_pet.core.tts_client import spoken_text
from desktop_pet.ui import icon_factory
from desktop_pet.ui.pronunciation_player import PronunciationPlayer
from desktop_pet.ui.pronunciation_worker import (
    PronunciationWorker,
    TTSNetConfig,
)

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# 喇叭三态
# --------------------------------------------------------------------------- #
STATE_NORMAL: str = "normal"
STATE_LOADING: str = "loading"
STATE_ERROR: str = "error"

_STATE_COLORS: dict[str, str] = {
    STATE_NORMAL: "text_primary",
    STATE_LOADING: "text_faint",
    STATE_ERROR: "text_faint",
}
_STATE_TIPS: dict[str, str] = {
    STATE_NORMAL: C.JP_SPEAKER_TIP,
    STATE_LOADING: C.JP_SPEAKER_LOADING_TIP,
    STATE_ERROR: C.JP_SPEAKER_ERROR_TIP,
}


class SpeakerButton(QLabel):
    """可点击喇叭图标（三态）；点击发 :attr:`clicked`，无业务逻辑。"""

    clicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        """构建喇叭按钮并进入常态。"""

        super().__init__(parent)
        self._size = QSize(C.SPACING["xl"], C.SPACING["xl"])
        self._state: str = STATE_NORMAL
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet("background: transparent;")
        self.set_state(STATE_NORMAL)

    @property
    def state(self) -> str:
        """当前三态（``normal`` / ``loading`` / ``error``）。"""

        return self._state

    def set_state(self, state: str, message: str = "") -> None:
        """切换三态视觉（未知状态按常态处理）。

        Args:
            state: ``STATE_NORMAL`` / ``STATE_LOADING`` / ``STATE_ERROR``。
            message: 失败态附带的原始错误（拼进 tooltip 便于排查）。
        """

        if state not in _STATE_COLORS:
            state = STATE_NORMAL
        self._state = state
        self.setPixmap(
            icon_factory.make_icon(
                "speaker", color=C.SEMANTIC_COLORS[_STATE_COLORS[state]]
            ).pixmap(self._size)
        )
        tip = _STATE_TIPS[state]
        if state == STATE_ERROR and message:
            tip = f"{tip}（{message}）"
        self.setToolTip(tip)

    def mousePressEvent(self, event) -> None:  # noqa: N802 —— Qt 命名约定
        """左键点击 → 发 :attr:`clicked`（获取中忽略，防重复排队）。

        事件就地消费不上抛：避免冒泡到父级（如生词卡片的选中逻辑）。
        """

        if event.button() == Qt.MouseButton.LeftButton and self._state != STATE_LOADING:
            event.accept()
            self.clicked.emit()
            return
        super().mousePressEvent(event)


class PronunciationController(QObject):
    """发音编排：缓存快路 → 后台抓取 → 播放；状态广播给两处喇叭。"""

    #: (key, state, message) —— key 为发音文本；窗口按当前词条过滤刷新
    state_changed = Signal(str, str, str)

    def __init__(
        self,
        pool: QThreadPool | None = None,
        cache: AudioCacheStore | None = None,
        player: QObject | None = None,
        net: TTSNetConfig | None = None,
        parent: QObject | None = None,
    ) -> None:
        """构造控制器（部件均可注入，供单测替换 fake）。"""

        super().__init__(parent)
        self._pool: QThreadPool = pool if pool is not None else QThreadPool(self)
        self._cache: AudioCacheStore = (
            cache if cache is not None else AudioCacheStore(AudioCacheStore.default_path())
        )
        self._player: QObject = (
            player if player is not None else PronunciationPlayer(self)
        )
        self._net: TTSNetConfig = net if net is not None else TTSNetConfig()
        self._busy: set[str] = set()
        self._player.play_failed.connect(self._on_play_failed)
        self.state_changed.connect(self._on_state_changed)

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def play(self, word: str, kana: str) -> None:
        """发音一个词：缓存命中直接播，未命中后台抓取（同词在途去重）。"""

        key = spoken_text(word, kana)
        if not key:
            return
        if key in self._busy:
            return
        cached = self._cache.load(key)
        if cached is not None:
            self._play_key(key, cached)
            return
        self._busy.add(key)
        self.state_changed.emit(key, STATE_LOADING, "")
        worker = PronunciationWorker(key, word, kana, self._cache, self._net)
        worker.signals.succeeded.connect(self._on_fetched)
        worker.signals.failed.connect(self._on_fetch_failed)
        self._pool.start(worker)

    def stop(self) -> None:
        """停止当前播放（无播放也安全）。"""

        self._player.stop()

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _play_key(self, key: str, path) -> None:
        """回到常态并播放（常态在播放前恢复，播放中按钮仍可点击重听）。"""

        self.state_changed.emit(key, STATE_NORMAL, "")
        self._player.play(key, path)

    def _on_fetched(self, key: str, path) -> None:
        """抓取成功 → 解除在途并播放。"""

        self._busy.discard(str(key))
        if path is None:
            logger.warning("发音抓取成功但无文件（%s）", key)
            return
        self._play_key(str(key), path)

    def _on_fetch_failed(self, key: str, message: str) -> None:
        """抓取失败 → 解除在途并广播错误态。"""

        self._busy.discard(str(key))
        self.state_changed.emit(str(key), STATE_ERROR, str(message))

    def _on_play_failed(self, key: str, message: str) -> None:
        """播放失败（多为缓存文件损坏）→ 删缓存 + 广播错误态。"""

        self._cache.discard(str(key))
        self.state_changed.emit(str(key), STATE_ERROR, str(message))

    def _on_state_changed(self, key: str, state: str, message: str) -> None:
        """兜底清在途（错误态保证下次点击可重试）。"""

        if state == STATE_ERROR:
            self._busy.discard(str(key))


__all__ = [
    "SpeakerButton",
    "PronunciationController",
    "STATE_NORMAL",
    "STATE_LOADING",
    "STATE_ERROR",
]
