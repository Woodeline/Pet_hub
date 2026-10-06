"""``ui.speaker_button`` 单测（喇叭三态 / 发音控制器编排，fake player 不真实出声）。

``WordDetailWindow`` / ``VocabWindow`` 的喇叭接线亦在此覆盖（fake controller 注入）。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from PySide6.QtCore import QObject, Qt, Signal

from desktop_pet.core import constants as C
from desktop_pet.core.audio_cache import AudioCacheStore
from desktop_pet.core.tts_client import spoken_text
from desktop_pet.core.vocabulary import VocabEntry
from desktop_pet.ui.speaker_button import (
    PronunciationController,
    STATE_ERROR,
    STATE_LOADING,
    STATE_NORMAL,
    SpeakerButton,
)
from desktop_pet.ui.vocab_window import VocabWindow
from desktop_pet.ui.word_detail_window import WordDetailWindow

_MP3 = b"\xff\xfb" + b"\x00" * 512


class _FakePlayer(QObject):
    """替身播放器：记录调用，可手动触发 play_failed。"""

    play_failed = Signal(str, str)

    def __init__(self) -> None:
        super().__init__()
        self.played: list[tuple[str, Path]] = []
        self.stop_count: int = 0

    def play(self, key: str, path) -> None:
        self.played.append((str(key), Path(path)))

    def stop(self) -> None:
        self.stop_count += 1


class _FakePool:
    """记录 start，不真正执行 runnable（由单测手动驱动 worker）。"""

    def __init__(self) -> None:
        self.started: list[object] = []

    def start(self, runnable: object) -> None:
        self.started.append(runnable)


@pytest.fixture()
def player(qapp) -> _FakePlayer:
    return _FakePlayer()


@pytest.fixture()
def cache(tmp_path) -> AudioCacheStore:
    return AudioCacheStore(tmp_path / "audio_cache")


# --------------------------------------------------------------------------- #
# 1. SpeakerButton 三态
# --------------------------------------------------------------------------- #
def test_speaker_button_click_emits(qtbot) -> None:
    button = SpeakerButton()
    qtbot.addWidget(button)

    with qtbot.waitSignal(button.clicked, timeout=1000):
        qtbot.mouseClick(button, Qt.MouseButton.LeftButton)


def test_speaker_button_click_ignored_while_loading(qtbot) -> None:
    button = SpeakerButton()
    qtbot.addWidget(button)
    button.set_state(STATE_LOADING)
    received: list = []
    button.clicked.connect(lambda: received.append(1))

    qtbot.mouseClick(button, Qt.MouseButton.LeftButton)

    assert received == []


def test_speaker_button_state_tooltips(qtbot) -> None:
    button = SpeakerButton()
    qtbot.addWidget(button)

    assert button.state == STATE_NORMAL
    assert button.toolTip() == C.JP_SPEAKER_TIP

    button.set_state(STATE_LOADING)
    assert button.toolTip() == C.JP_SPEAKER_LOADING_TIP

    button.set_state(STATE_ERROR, "boom")
    assert C.JP_SPEAKER_ERROR_TIP in button.toolTip()
    assert "boom" in button.toolTip()

    button.set_state("nonsense")  # 未知态按常态处理
    assert button.state == STATE_NORMAL


# --------------------------------------------------------------------------- #
# 2. PronunciationController（fake pool 手动驱动 worker）
# --------------------------------------------------------------------------- #
def _controller(player, cache) -> tuple[PronunciationController, _FakePool]:
    pool = _FakePool()
    return PronunciationController(pool=pool, cache=cache, player=player), pool


def test_play_cache_hit_plays_immediately(qtbot, player, cache) -> None:
    controller, pool = _controller(player, cache)
    cache.save("わたし", _MP3)  # 发音键 = 假名（spoken_text 优先假名）
    states: list[tuple[str, str]] = []
    controller.state_changed.connect(
        lambda key, state, msg: states.append((state, msg))
    )

    controller.play("私", "わたし")

    assert pool.started == []  # 未发起后台抓取
    assert player.played == [("わたし", cache.path_for("わたし"))]
    assert states == [(STATE_NORMAL, "")]


def test_play_miss_starts_worker_and_emits_loading(qtbot, player, cache) -> None:
    controller, pool = _controller(player, cache)
    states: list[str] = []
    controller.state_changed.connect(
        lambda key, state, msg: states.append(state)
    )

    controller.play("私", "わたし")

    assert len(pool.started) == 1
    assert states == [STATE_LOADING]
    assert player.played == []  # worker 尚未手动驱动


def test_play_dedupes_same_key_while_busy(qtbot, player, cache) -> None:
    controller, pool = _controller(player, cache)

    controller.play("私", "わたし")
    controller.play("私", "わたし")

    assert len(pool.started) == 1


def test_worker_success_plays_and_saves(qtbot, player, cache, monkeypatch) -> None:
    controller, pool = _controller(player, cache)
    monkeypatch.setattr(
        "desktop_pet.core.tts_client.urllib.request.urlopen",
        _fake_urlopen_factory(_MP3_BYTES),
    )
    states: list[str] = []
    controller.state_changed.connect(
        lambda key, state, msg: states.append(state)
    )

    controller.play("私", "わたし")
    _drive(pool)  # 手动执行 worker.run()

    assert cache.load("わたし") is not None
    assert player.played and player.played[-1][0] == "わたし"
    assert states == [STATE_LOADING, STATE_NORMAL]


def test_worker_failure_emits_error_and_recoverable(
    qtbot, player, cache, monkeypatch
) -> None:
    import urllib.error

    controller, pool = _controller(player, cache)

    def boom(request, timeout=None):
        raise urllib.error.URLError("offline")

    monkeypatch.setattr(
        "desktop_pet.core.tts_client.urllib.request.urlopen", boom
    )
    states: list[str] = []
    controller.state_changed.connect(
        lambda key, state, msg: states.append(state)
    )

    controller.play("私", "わたし")
    _drive(pool)

    assert states == [STATE_LOADING, STATE_ERROR]
    # 失败解除在途：可再次点击（再次排队；_drive 已清空队列，故长度回到 1）
    controller.play("私", "わたし")
    assert len(pool.started) == 1


def test_play_failed_discards_cache(qtbot, player, cache) -> None:
    controller, pool = _controller(player, cache)
    cache.save("わたし", b"\x00corrupt")
    states: list[str] = []
    controller.state_changed.connect(
        lambda key, state, msg: states.append(state)
    )

    controller.play("私", "わたし")
    assert cache.load("わたし") is not None

    player.play_failed.emit("わたし", "decode error")
    _drive(pool)  # no-op，仅保证事件循环一致

    assert cache.load("わたし") is None
    assert states[-1] == STATE_ERROR


def test_stop_forwards_to_player(qtbot, player, cache) -> None:
    controller, pool = _controller(player, cache)

    controller.stop()

    assert player.stop_count == 1


def _drive(pool: _FakePool) -> None:
    """手动执行 fake pool 中排队的所有 runnable（worker.run() 在本线程同步跑）。"""

    while pool.started:
        runnable = pool.started.pop(0)
        runnable.run()


# ``test_worker_success_plays_and_saves`` 用的假 urlopen 工厂（模块级便于复用）
_MP3_BYTES = b"\xff\xfb" + b"\x00" * 1024


def _fake_urlopen_factory(body: bytes):
    class _Resp:
        status = 200
        headers = {"Content-Type": "audio/mpeg"}

        def read(self) -> bytes:
            return body

        def __enter__(self):
            return self

        def __exit__(self, *exc_info) -> bool:
            return False

    def fake_urlopen(request, timeout=None):
        return _Resp()

    return fake_urlopen


# --------------------------------------------------------------------------- #
# 3. 详情窗喇叭接线
# --------------------------------------------------------------------------- #
def _entry() -> VocabEntry:
    return VocabEntry(
        id="n5-0001", level="N5", word="私", kana="わたし",
        translation="我", meaning="第一人称代词", romaji="watashi",
    )


def test_detail_window_speaker_forwards_play(qtbot) -> None:
    controller, pool = _controller_player()
    window = WordDetailWindow(pool=_FakePool(), pronunciation=controller)
    qtbot.addWidget(window)
    window.show_entry(_entry())

    window._speaker.clicked.emit()

    assert len(pool.started) == 1


def test_detail_window_speaker_state_refresh(qtbot) -> None:
    controller, pool = _controller_player()
    window = WordDetailWindow(pool=_FakePool(), pronunciation=controller)
    qtbot.addWidget(window)
    window.show_entry(_entry())
    key = spoken_text("私", "わたし")

    controller.state_changed.emit(key, STATE_LOADING, "")
    assert window._speaker.state == STATE_LOADING

    controller.state_changed.emit(key, STATE_NORMAL, "")
    assert window._speaker.state == STATE_NORMAL

    controller.state_changed.emit(key, STATE_ERROR, "boom")
    assert window._speaker.state == STATE_ERROR
    # 底部状态行空闲（详情流程未占用）时借用提示
    assert window._status_label.text() == C.JP_SPEAKER_ERROR_TIP


def test_detail_window_ignores_other_word_state(qtbot) -> None:
    controller, pool = _controller_player()
    window = WordDetailWindow(pool=_FakePool(), pronunciation=controller)
    qtbot.addWidget(window)
    window.show_entry(_entry())

    controller.state_changed.emit("别的词", STATE_ERROR, "boom")

    assert window._speaker.state == STATE_NORMAL


def test_detail_window_without_pronunciation_is_inert(qtbot) -> None:
    window = WordDetailWindow(pool=_FakePool())
    qtbot.addWidget(window)
    window.show_entry(_entry())

    window._speaker.clicked.emit()  # 不抛即可（无控制器，喇叭保持常态）

    assert window._speaker.state == STATE_NORMAL


def _controller_player() -> tuple[PronunciationController, _FakePool]:
    pool = _FakePool()
    player = _FakePlayer()
    controller = PronunciationController(pool=pool, player=player)
    return controller, pool


# --------------------------------------------------------------------------- #
# 4. 生词本卡片喇叭接线
# --------------------------------------------------------------------------- #
def test_vocab_window_card_speaker_forwards_play(qtbot) -> None:
    controller, pool = _controller_player()
    window = VocabWindow(pronunciation=controller)
    qtbot.addWidget(window)
    window.refresh([_vocab_item()])

    card = next(iter(window._card_by_id.values()))
    card._speaker.clicked.emit()

    assert len(pool.started) == 1


def test_vocab_window_state_refreshes_matching_card(qtbot) -> None:
    controller, pool = _controller_player()
    window = VocabWindow(pronunciation=controller)
    qtbot.addWidget(window)
    window.refresh([_vocab_item()])
    card = next(iter(window._card_by_id.values()))

    controller.state_changed.emit("わたし", STATE_LOADING, "")
    assert card._speaker.state == STATE_LOADING

    controller.state_changed.emit("别的词", STATE_ERROR, "boom")
    assert card._speaker.state == STATE_LOADING  # 不受他词状态影响

    controller.state_changed.emit("わたし", STATE_NORMAL, "")
    assert card._speaker.state == STATE_NORMAL


def test_vocab_window_without_pronunciation_ignores_play(qtbot) -> None:
    window = VocabWindow()
    qtbot.addWidget(window)
    window.refresh([_vocab_item()])
    card = next(iter(window._card_by_id.values()))

    card._speaker.clicked.emit()  # 不抛即可

    assert card._speaker.state == STATE_NORMAL


def _vocab_item():
    from desktop_pet.core.vocab_store import VocabItem

    return VocabItem(
        id="n5-0001", level="N5", word="私", kana="わたし",
        translation="我", meaning="第一人称代词", added_at="2026-10-01T00:00:00",
    )
