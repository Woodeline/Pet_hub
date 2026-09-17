"""core.jisho 单测（URL 构造 / 解析 / 无结果 / 异常）。

联网函数通过 monkeypatch 掉 ``urllib.request.urlopen``，测试不发真实请求。
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.jisho import (
    JishoError,
    JishoNotFound,
    JishoResult,
    build_url,
    fetch,
    parse,
)


def _result() -> JishoResult:
    return JishoResult(
        word="食べる",
        readings=("たべる",),
        parts_of_speech=("Ichidan verb", "Transitive verb"),
        english_definitions=("to eat",),
        jlpt=("N5",),
        is_common=True,
    )


def _payload() -> dict:
    return {
        "data": [
            {
                "slug": "たべる",
                "japanese": [{"word": "食べる", "reading": "たべる"}],
                "senses": [
                    {
                        "parts_of_speech": ["Ichidan verb", "Transitive verb"],
                        "english_definitions": ["to eat"],
                    }
                ],
                "jlpt": ["N5"],
                "is_common": True,
            }
        ]
    }


class _FakeResponse:
    """模拟 ``urllib.request.urlopen`` 返回的上下文管理器。"""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


# --------------------------------------------------------------------------- #
# 1. URL 构造
# --------------------------------------------------------------------------- #
def test_build_url_encodes_keyword() -> None:
    assert build_url("食べる") == f"{C.JISHO_API_URL}?keyword=%E9%A3%9F%E3%81%B9%E3%82%8B"


def test_build_url_encodes_spaces() -> None:
    assert build_url("to eat") == f"{C.JISHO_API_URL}?keyword=to%20eat"


# --------------------------------------------------------------------------- #
# 2. parse（纯函数）
# --------------------------------------------------------------------------- #
def test_parse_valid_payload() -> None:
    assert parse(_payload()) == _result()


def test_parse_no_data_returns_none() -> None:
    assert parse({"data": []}) is None
    assert parse({"data": "not-list"}) is None
    assert parse({}) is None
    assert parse("not-dict") is None


def test_parse_entry_without_word_returns_none() -> None:
    assert parse({"data": [{"slug": "", "japanese": []}]}) is None


def test_parse_max_definitions_capped() -> None:
    payload = {
        "data": [
            {
                "slug": "x",
                "japanese": [{"word": "x"}],
                "senses": [
                    {"parts_of_speech": [], "english_definitions": [f"def{i}" for i in range(20)]}
                ],
            }
        ]
    }
    result = parse(payload)
    assert result is not None
    assert len(result.english_definitions) == C.JISHO_MAX_DEFINITIONS


# --------------------------------------------------------------------------- #
# 3. JishoResult 序列化
# --------------------------------------------------------------------------- #
def test_jisho_result_roundtrip() -> None:
    assert JishoResult.from_dict(_result().to_dict()) == _result()


def test_jisho_result_from_dict_missing_word_returns_none() -> None:
    assert JishoResult.from_dict({"readings": []}) is None
    assert JishoResult.from_dict(None) is None
    assert JishoResult.from_dict("x") is None


def test_jisho_result_from_dict_lenient() -> None:
    assert JishoResult.from_dict({"word": "x"}) == JishoResult("x", (), (), (), (), False)


# --------------------------------------------------------------------------- #
# 4. fetch（monkeypatch 掉 urlopen）
# --------------------------------------------------------------------------- #
def test_fetch_returns_result(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, str] = {}

    def fake_urlopen(request: object, timeout: float) -> _FakeResponse:
        captured["url"] = getattr(request, "full_url", "")
        captured["timeout"] = str(timeout)
        return _FakeResponse(json.dumps(_payload()).encode("utf-8"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    assert fetch("食べる") == _result()
    assert captured["url"] == build_url("食べる")
    assert captured["timeout"] == str(C.JISHO_TIMEOUT_S)


def test_fetch_not_found_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResponse(b'{"data": []}'),
    )
    with pytest.raises(JishoNotFound):
        fetch("nope")


def test_fetch_network_error_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_urlopen(request: object, timeout: float) -> None:
        raise urllib.error.URLError("boom")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(JishoError):
        fetch("食べる")


def test_fetch_invalid_json_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResponse(b"not-json"),
    )
    with pytest.raises(JishoError):
        fetch("食べる")


def test_fetch_empty_keyword_raises() -> None:
    with pytest.raises(JishoError):
        fetch("")
    with pytest.raises(JishoError):
        fetch("   ")
