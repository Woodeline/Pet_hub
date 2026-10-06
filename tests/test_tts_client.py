"""``core.tts_client`` 单测（mock urllib：URL/UA + 多源回退 + 异常分类）。

``ui.pronunciation_worker`` 的 ``run()`` 亦在此覆盖（缓存命中 / 落盘 / 失败 / 绝不裸抛）。
"""

from __future__ import annotations

import urllib.error

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import tts_client
from desktop_pet.core.audio_cache import AudioCacheStore
from desktop_pet.core.tts_client import (
    TTSClient,
    TTSConfigError,
    TTSError,
    TTSNetworkError,
    TTSParseError,
    spoken_text,
)
from desktop_pet.ui.pronunciation_worker import (
    PronunciationWorker,
    TTSNetConfig,
)

_MP3 = b"\xff\xfb" + b"\x00" * 1024  # 合法 MP3 头 + 足够长的正文


class _FakeAudioResponse:
    """模拟 ``urlopen`` 返回的上下文管理器音频响应对象。"""

    def __init__(self, body: bytes, content_type: str = "audio/mpeg") -> None:
        self._body = body
        self.status = 200
        self.headers = {"Content-Type": content_type}

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeAudioResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


@pytest.fixture()
def capture_urlopen(monkeypatch: pytest.MonkeyPatch):
    """把 ``urllib.request.urlopen`` 换为可编程假实现，并记录请求细节。"""

    captured: dict[str, object] = {}

    def factory(result):
        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["headers"] = {
                str(key).lower(): value for key, value in request.header_items()
            }
            captured["timeout"] = timeout
            captured["calls"] = captured.get("calls", 0) + 1
            if isinstance(result, Exception):
                raise result
            if isinstance(result, tuple):
                # (body, content_type) 形式
                return _FakeAudioResponse(*result)
            return _FakeAudioResponse(result)

        monkeypatch.setattr(tts_client.urllib.request, "urlopen", fake_urlopen)
        return captured

    return factory


# --------------------------------------------------------------------------- #
# 1. spoken_text（优先假名 —— 纠错机制）
# --------------------------------------------------------------------------- #
def test_spoken_text_prefers_kana() -> None:
    # 明後日=あさって 熟字训：汉字字面拼读必错，假名即读音真相
    assert spoken_text("明後日", "あさって") == "あさって"


def test_spoken_text_word_fallback_when_kana_empty() -> None:
    assert spoken_text("私", "") == "私"
    assert spoken_text("私", None) == "私"  # type: ignore[arg-type]


def test_spoken_text_impure_kana_falls_back_to_word() -> None:
    # 假名字段混入拉丁/汉字/数字 → 视为脏数据，宁可信词头
    assert spoken_text("私", "watashi") == "私"
    assert spoken_text("私", "わたし 私") == "私"
    assert spoken_text("3日", "3にち") == "3日"


def test_spoken_text_impure_kana_used_when_word_empty() -> None:
    # 词头也缺时，脏假名仍是唯一选择
    assert spoken_text("", "watashi") == "watashi"


def test_spoken_text_both_empty() -> None:
    assert spoken_text("", "") == ""


def test_spoken_text_pure_kana_including_prolonged_mark() -> None:
    assert spoken_text("コーヒー", "コーヒー") == "コーヒー"


# --------------------------------------------------------------------------- #
# 2. fetch（mock urlopen）
# --------------------------------------------------------------------------- #
def test_fetch_success_request_shape(capture_urlopen) -> None:
    captured = capture_urlopen(_MP3)
    client = TTSClient(timeout_s=3.0)

    data = client.fetch("私", "わたし")

    assert data == _MP3
    assert captured["timeout"] == 3.0
    assert captured["calls"] == 1  # 主源（有道）一次成功，不碰回退源
    url = str(captured["url"])
    assert url.startswith("https://dict.youdao.com/dictvoice?")
    assert "le=ja" in url
    import urllib.parse

    assert f"audio={urllib.parse.quote('わたし')}" in url  # 优先假名
    headers = captured["headers"]
    assert "user-agent" in headers


def test_fetch_falls_back_to_google_on_network_error(capture_urlopen, monkeypatch) -> None:
    import urllib.parse

    calls: list[str] = []

    def flaky(request, timeout=None):
        calls.append(request.full_url)
        if len(calls) == 1:
            raise urllib.error.URLError("youdao unreachable")
        assert request.full_url.startswith("https://translate.google.com/translate_tts?")
        assert f"tl={C.TTS_LANG}" in request.full_url
        assert f"q={urllib.parse.quote('わたし')}" in request.full_url  # 优先假名
        return _FakeAudioResponse(_MP3)

    monkeypatch.setattr(tts_client.urllib.request, "urlopen", flaky)
    client = TTSClient(timeout_s=3.0)

    data = client.fetch("私", "わたし")

    assert data == _MP3
    assert len(calls) == 2


def test_fetch_uses_kana_when_word_empty(capture_urlopen) -> None:
    import urllib.parse

    captured = capture_urlopen(_MP3)
    client = TTSClient(timeout_s=3.0)

    client.fetch("", "わたし")

    assert f"audio={urllib.parse.quote('わたし')}" in str(captured["url"])


def test_fetch_empty_text_config_error_no_request(capture_urlopen) -> None:
    captured = capture_urlopen(_MP3)
    client = TTSClient()

    with pytest.raises(TTSConfigError):
        client.fetch("", "")

    assert captured.get("calls", 0) == 0


def test_fetch_all_sources_network_error_wrapped(capture_urlopen) -> None:
    capture_urlopen(urllib.error.URLError("offline"))
    client = TTSClient(timeout_s=1.0)

    with pytest.raises(TTSNetworkError):
        client.fetch("私", "わたし")


def test_fetch_non_audio_content_type_parse_error(capture_urlopen) -> None:
    capture_urlopen((b"<html>error page</html>", "text/html"))
    client = TTSClient(timeout_s=1.0)

    with pytest.raises(TTSParseError):
        client.fetch("私", "わたし")


def test_fetch_too_short_body_parse_error(capture_urlopen) -> None:
    capture_urlopen((b"\xff\xfb\x00", "audio/mpeg"))
    client = TTSClient(timeout_s=1.0)

    with pytest.raises(TTSParseError):
        client.fetch("私", "わたし")


def test_tts_error_family() -> None:
    assert issubclass(TTSConfigError, TTSError)
    assert issubclass(TTSNetworkError, TTSError)
    assert issubclass(TTSParseError, TTSError)


# --------------------------------------------------------------------------- #
# 3. PronunciationWorker.run（缓存 + 落盘 + 绝不裸抛）
# --------------------------------------------------------------------------- #
def _worker(key: str, cache: AudioCacheStore) -> PronunciationWorker:
    return PronunciationWorker(
        key,
        key,
        "わたし",
        cache,
        TTSNetConfig(timeout_s=1.0),
    )


def test_worker_cache_hit_no_network(qtbot, tmp_path, capture_urlopen) -> None:
    cache = AudioCacheStore(tmp_path / "audio_cache")
    cache.save("私", _MP3)
    captured = capture_urlopen(_MP3)

    worker = _worker("私", cache)
    with qtbot.waitSignal(worker.signals.succeeded, timeout=3000) as blocker:
        worker.run()

    key, path = blocker.args
    assert key == "私"
    assert path is not None and path.is_file()
    assert captured.get("calls", 0) == 0  # 命中缓存，未联网


def test_worker_fetches_and_saves(qtbot, tmp_path, capture_urlopen) -> None:
    cache = AudioCacheStore(tmp_path / "audio_cache")
    capture_urlopen(_MP3)

    worker = _worker("私", cache)
    with qtbot.waitSignal(worker.signals.succeeded, timeout=3000) as blocker:
        worker.run()

    key, path = blocker.args
    assert key == "私"
    assert path is not None and path.is_file()
    assert path.read_bytes() == _MP3
    assert cache.load("私") == path  # 已落盘，下次命中


def test_worker_save_failure_falls_back_to_temp(
    qtbot, tmp_path, capture_urlopen, monkeypatch
) -> None:
    cache = AudioCacheStore(tmp_path / "audio_cache")
    capture_urlopen(_MP3)
    monkeypatch.setattr(cache, "save", lambda text, data: None)

    worker = _worker("私", cache)
    with qtbot.waitSignal(worker.signals.succeeded, timeout=3000) as blocker:
        worker.run()

    _, path = blocker.args
    assert path is not None and path.is_file()
    assert path.suffix == ".mp3"


def test_worker_failure_never_raises(qtbot, tmp_path, capture_urlopen) -> None:
    cache = AudioCacheStore(tmp_path / "audio_cache")
    capture_urlopen(urllib.error.URLError("offline"))

    worker = _worker("私", cache)
    with qtbot.waitSignal(worker.signals.failed, timeout=3000) as blocker:
        worker.run()

    key, message = blocker.args
    assert key == "私"
    assert message
