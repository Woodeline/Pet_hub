"""``core.llm_client`` 单测（mock urllib：URL/鉴权头/body + JSON 提取容错 + 异常分类）。

``ui.word_detail_worker`` 的 ``run()`` 亦在此覆盖（成功 / 失败 / 绝不裸抛）。
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import llm_client
from desktop_pet.core.llm_client import (
    DeepSeekClient,
    LLMAuthError,
    LLMConfigError,
    LLMError,
    LLMNetworkError,
    LLMParseError,
)
from desktop_pet.core.word_detail import WordDetail
from desktop_pet.ui.word_detail_worker import (
    WordDetailNetConfig,
    WordDetailWorker,
)

_API_KEY = "sk-test-123"
_DETAIL = {
    C.WORD_DETAIL_FIELD_MEANING: ["我"],
    C.WORD_DETAIL_FIELD_POS: ["代词"],
    C.WORD_DETAIL_FIELD_COLLOCATIONS: [{"phrase": "私は…", "note": "自我介绍"}],
    C.WORD_DETAIL_FIELD_EXAMPLES: [{"jp": "私は学生です。", "zh": "我是学生。"}],
    C.WORD_DETAIL_FIELD_USAGE: "正式、通用。",
}


class _FakeResponse:
    """模拟 ``urlopen`` 返回的上下文管理器响应对象。"""

    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


def _envelope(content: str) -> str:
    """把模型输出内容包装成 OpenAI 兼容响应信封。"""

    return json.dumps(
        {"choices": [{"message": {"role": "assistant", "content": content}}]},
        ensure_ascii=False,
    )


@pytest.fixture()
def capture_urlopen(monkeypatch: pytest.MonkeyPatch):
    """把 ``urllib.request.urlopen`` 换为可编程假实现，并记录请求细节。"""

    captured: dict[str, object] = {}

    def factory(result):
        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["headers"] = {
                str(key).lower(): value for key, value in request.header_items()
            }
            raw = request.data.decode("utf-8") if request.data else ""
            captured["data"] = json.loads(raw) if raw else {}
            captured["timeout"] = timeout
            captured["calls"] = captured.get("calls", 0) + 1
            if isinstance(result, Exception):
                raise result
            return _FakeResponse(result)

        monkeypatch.setattr(llm_client.urllib.request, "urlopen", fake_urlopen)
        return captured

    return factory


# --------------------------------------------------------------------------- #
# 1. build_prompt
# --------------------------------------------------------------------------- #
def test_build_prompt_structure_and_substitution() -> None:
    messages = DeepSeekClient.build_prompt("私", kana="わたし", level="N5", translation="我")
    assert [m["role"] for m in messages] == ["system", "user"]
    assert messages[0]["content"] == C.LLM_PROMPT_SYSTEM
    user = messages[1]["content"]
    assert "私" in user and "わたし" in user and "N5" in user and "我" in user
    # JSON 花括号已正确转义（单花括号一次出现，而非双花括号）
    assert '{"meaning_zh"' in user
    assert "{{" not in user


def test_build_prompt_blank_fields_use_placeholder() -> None:
    messages = DeepSeekClient.build_prompt("私")
    assert C.WORD_DETAIL_NO_VALUE in messages[1]["content"]


# --------------------------------------------------------------------------- #
# 2. _extract_json 容错
# --------------------------------------------------------------------------- #
def test_extract_json_bare_object() -> None:
    text = json.dumps(_DETAIL, ensure_ascii=False)
    assert DeepSeekClient._extract_json(text) == _DETAIL


def test_extract_json_with_code_fence() -> None:
    text = "```json\n" + json.dumps(_DETAIL, ensure_ascii=False) + "\n```"
    assert DeepSeekClient._extract_json(text) == _DETAIL


def test_extract_json_with_surrounding_text() -> None:
    text = "好的，结果如下：" + json.dumps(_DETAIL, ensure_ascii=False) + " 完毕。"
    assert DeepSeekClient._extract_json(text) == _DETAIL


def test_extract_json_ignores_braces_inside_strings() -> None:
    payload = {C.WORD_DETAIL_FIELD_USAGE: "含 {花括号} 的说明", C.WORD_DETAIL_FIELD_MEANING: ["我"]}
    text = "前缀 " + json.dumps(payload, ensure_ascii=False) + " 后缀"
    assert DeepSeekClient._extract_json(text) == payload


def test_extract_json_from_envelope() -> None:
    text = _envelope(json.dumps(_DETAIL, ensure_ascii=False))
    assert DeepSeekClient._extract_json(text) == _DETAIL


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "no json here at all",
        '{"meaning_zh": ["我"',  # 截断，无匹配 }
        "[1, 2, 3]",             # 已解析但非对象 → 无 { 可截取
    ],
)
def test_extract_json_invalid_raises_parse_error(bad: str) -> None:
    with pytest.raises(LLMParseError):
        DeepSeekClient._extract_json(bad)


# --------------------------------------------------------------------------- #
# 3. fetch_word_detail（mock urlopen）
# --------------------------------------------------------------------------- #
def _client(**overrides) -> DeepSeekClient:
    params = {
        "api_key": _API_KEY,
        "base_url": C.LLM_ENDPOINT,
        "model": C.LLM_MODEL,
        "timeout_s": C.LLM_TIMEOUT_S,
        "retries": 1,
    }
    params.update(overrides)
    return DeepSeekClient(**params)


def test_fetch_success_request_shape(capture_urlopen) -> None:
    captured = capture_urlopen(_envelope(json.dumps(_DETAIL, ensure_ascii=False)))
    detail = _client().fetch_word_detail("私", "わたし", "N5", "我")

    assert detail == WordDetail.from_dict(_DETAIL)
    assert captured["url"] == C.LLM_ENDPOINT
    assert captured["method"] == "POST"
    assert captured["headers"]["authorization"] == f"Bearer {_API_KEY}"
    assert captured["headers"]["content-type"] == "application/json"
    body = captured["data"]
    assert body["model"] == C.LLM_MODEL
    assert body["response_format"] == {"type": "json_object"}
    assert body["messages"][0]["role"] == "system"
    assert captured["timeout"] == C.LLM_TIMEOUT_S
    assert captured["calls"] == 1


def test_fetch_empty_key_raises_config_error_without_request(capture_urlopen) -> None:
    captured = capture_urlopen(_envelope(json.dumps(_DETAIL, ensure_ascii=False)))
    with pytest.raises(LLMConfigError):
        _client(api_key="").fetch_word_detail("私")
    assert captured.get("calls", 0) == 0


def test_fetch_blank_word_raises_config_error(capture_urlopen) -> None:
    capture_urlopen(_envelope(json.dumps(_DETAIL, ensure_ascii=False)))
    with pytest.raises(LLMConfigError):
        _client().fetch_word_detail("   ")


def test_fetch_401_raises_auth_error_without_retry(capture_urlopen) -> None:
    captured = capture_urlopen(
        urllib.error.HTTPError(C.LLM_ENDPOINT, 401, "Unauthorized", {}, None)
    )
    with pytest.raises(LLMAuthError):
        _client().fetch_word_detail("私")
    assert captured["calls"] == 1  # 鉴权失败不重试


def test_fetch_403_raises_auth_error(capture_urlopen) -> None:
    capture_urlopen(urllib.error.HTTPError(C.LLM_ENDPOINT, 403, "Forbidden", {}, None))
    with pytest.raises(LLMAuthError):
        _client().fetch_word_detail("私")


def test_fetch_network_error_retries(capture_urlopen) -> None:
    captured = capture_urlopen(urllib.error.URLError("boom"))
    with pytest.raises(LLMNetworkError):
        _client(retries=1).fetch_word_detail("私")
    assert captured["calls"] == 2  # 1 次 + 重试 1 次


def test_fetch_timeout_raises_network_error(capture_urlopen) -> None:
    capture_urlopen(TimeoutError("timed out"))
    with pytest.raises(LLMNetworkError):
        _client(retries=0).fetch_word_detail("私")


def test_fetch_http_500_is_network_error_and_retries(capture_urlopen) -> None:
    captured = capture_urlopen(
        urllib.error.HTTPError(C.LLM_ENDPOINT, 500, "Server Error", {}, None)
    )
    with pytest.raises(LLMNetworkError):
        _client(retries=1).fetch_word_detail("私")
    assert captured["calls"] == 2


def test_fetch_bad_json_raises_parse_error(capture_urlopen) -> None:
    capture_urlopen("totally not json")
    with pytest.raises(LLMParseError):
        _client().fetch_word_detail("私")


def test_fetch_all_empty_detail_raises_parse_error(capture_urlopen) -> None:
    capture_urlopen(_envelope("{}"))
    with pytest.raises(LLMParseError):
        _client().fetch_word_detail("私")


# --------------------------------------------------------------------------- #
# 4. WordDetailWorker（run 绝不裸抛）
# --------------------------------------------------------------------------- #
def _net() -> WordDetailNetConfig:
    return WordDetailNetConfig(
        api_key=_API_KEY,
        base_url=C.LLM_ENDPOINT,
        model=C.LLM_MODEL,
        timeout_s=C.LLM_TIMEOUT_S,
        retries=0,
    )


def test_worker_success_emits_succeeded(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(
            _envelope(json.dumps(_DETAIL, ensure_ascii=False))
        ),
    )
    worker = WordDetailWorker("n5-0001", "私", "わたし", "N5", "我", _net())
    got: list[tuple[str, object]] = []
    worker.signals.succeeded.connect(lambda iid, detail: got.append((iid, detail)))

    worker.run()  # 同步执行，直接触发 DirectConnection

    assert len(got) == 1
    assert got[0][0] == "n5-0001"
    assert got[0][1] == WordDetail.from_dict(_DETAIL)


def test_worker_failure_emits_failed(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(request, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(llm_client.urllib.request, "urlopen", boom)
    worker = WordDetailWorker("n5-0001", "私", "", "N5", "", _net())
    failed: list[tuple[str, str]] = []
    worker.signals.failed.connect(lambda iid, msg: failed.append((iid, msg)))

    worker.run()

    assert len(failed) == 1
    assert failed[0][0] == "n5-0001"
    assert failed[0][1]


def test_worker_unexpected_exception_never_raises(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    def explode(self, *args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(DeepSeekClient, "fetch_word_detail", explode)
    worker = WordDetailWorker("n5-0001", "私", "", "N5", "", _net())
    failed: list[tuple[str, str]] = []
    worker.signals.failed.connect(lambda iid, msg: failed.append((iid, msg)))

    worker.run()  # 不应抛出

    assert len(failed) == 1
    assert "unexpected" in failed[0][1]


def test_worker_none_net_emits_failed(qtbot) -> None:
    worker = WordDetailWorker("n5-0001", "私", "", "N5", "", None)  # type: ignore[arg-type]
    failed: list[tuple[str, str]] = []
    worker.signals.failed.connect(lambda iid, msg: failed.append((iid, msg)))
    worker.run()
    assert len(failed) == 1


def test_worker_llm_config_error_is_failed(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        llm_client.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse("{}"),
    )
    worker = WordDetailWorker(
        "n5-0001", "私", "", "N5", "",
        WordDetailNetConfig("", C.LLM_ENDPOINT, C.LLM_MODEL, C.LLM_TIMEOUT_S, 0),
    )
    failed: list[tuple[str, str]] = []
    worker.signals.failed.connect(lambda iid, msg: failed.append((iid, msg)))
    worker.run()
    assert len(failed) == 1
    assert isinstance(failed[0][1], str)


def test_llm_error_hierarchy() -> None:
    for exc in (LLMAuthError, LLMNetworkError, LLMParseError, LLMConfigError):
        assert issubclass(exc, LLMError)
