"""工程师自测：core.update_client —— 检查更新纯逻辑（版本比较 + GitHub 查询）。

覆盖：
1. parse_version / is_newer 全矩阵（含脏输入一律「不更新」）。
2. fetch_latest_release：monkeypatch urlopen（网络全 mock，不发真实请求）——
   成功解析、HTTP 错误、网络不可达、JSON 非法、缺 tag_name、请求头（UA/Accept）。
3. ui.update_worker：成功 / 失败信号路由（QThreadPool 不实际起线程，直接 run()）。

core 零时钟约定：本模块不做任何日期算术（7 天间隔判定在 app 层测试覆盖）。
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core import update_client
from desktop_pet.core.update_client import (
    ReleaseInfo,
    UpdateCheckError,
    fetch_latest_release,
    is_newer,
    parse_version,
)
from desktop_pet.ui.update_worker import UpdateCheckWorker

_RELEASE_ENVELOPE = json.dumps(
    {
        "tag_name": "v9.9.9",
        "name": "v9.9.9 大版本",
        "html_url": "https://github.com/Woodeline/Pet_hub/releases/tag/v9.9.9",
    }
)


class _FakeResponse:
    """模拟 ``urlopen`` 返回的上下文管理器响应对象（status 属性形态）。"""

    def __init__(self, body: str, status: int = 200) -> None:
        self._body = body.encode("utf-8")
        self.status = status

    def read(self) -> bytes:
        return self._body

    def getcode(self) -> int:
        return self.status

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc_info) -> bool:
        return False


@pytest.fixture()
def capture_urlopen(monkeypatch: pytest.MonkeyPatch):
    """把 ``update_client`` 视角下的 ``urlopen`` 换为可编程假实现并记录请求。"""

    captured: dict[str, object] = {}

    def factory(result):
        def fake_urlopen(request, timeout=None):
            captured["url"] = request.full_url
            captured["method"] = request.get_method()
            captured["headers"] = {
                str(key).lower(): value for key, value in request.header_items()
            }
            captured["timeout"] = timeout
            captured["calls"] = captured.get("calls", 0) + 1
            if isinstance(result, Exception):
                raise result
            return _FakeResponse(result)

        monkeypatch.setattr(update_client.urllib.request, "urlopen", fake_urlopen)
        return captured

    return factory


# --------------------------------------------------------------------------- #
# 版本比较
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "text,expected",
    [
        ("v0.6.2", (0, 6, 2)),
        ("V1.2.3", (1, 2, 3)),
        ("0.6.2", (0, 6, 2)),
        ("  v0.6.10 ", (0, 6, 10)),
    ],
)
def test_parse_version_valid(text: str, expected) -> None:
    assert parse_version(text) == expected


@pytest.mark.parametrize(
    "text",
    ["", "abc", "v1", "1.2", "1.2.3.4", "v1.2.x", "v1.2.3-beta"],
)
def test_parse_version_invalid_returns_none(text: str) -> None:
    assert parse_version(text) is None


@pytest.mark.parametrize(
    "remote,local,expected",
    [
        ("v0.7.0", "0.6.2", True),
        ("v0.6.2", "0.6.2", False),
        ("v0.6.1", "0.6.2", False),
        ("v0.10.0", "0.9.9", True),
        ("garbage", "0.6.2", False),
        ("v9.9.9", "garbage", False),
    ],
)
def test_is_newer_matrix(remote: str, local: str, expected: bool) -> None:
    assert is_newer(remote, local) is expected


# --------------------------------------------------------------------------- #
# fetch_latest_release（网络全 mock）
# --------------------------------------------------------------------------- #
def test_fetch_success_parses_release(capture_urlopen) -> None:
    captured = capture_urlopen(_RELEASE_ENVELOPE)

    release = fetch_latest_release(timeout_s=3.0)

    assert release == ReleaseInfo(
        tag_name="v9.9.9",
        name="v9.9.9 大版本",
        html_url="https://github.com/Woodeline/Pet_hub/releases/tag/v9.9.9",
    )
    assert captured["url"] == C.UPDATE_GITHUB_RELEASES_URL
    assert captured["method"] == "GET"
    headers = captured["headers"]
    assert any("user-agent" in key and "desktop-pet" in value for key, value in headers.items())
    assert any("accept" in key and "vnd.github+json" in value for key, value in headers.items())
    assert captured["timeout"] == 3.0


def test_fetch_http_error_raises(capture_urlopen) -> None:
    capture_urlopen(urllib.error.HTTPError(C.UPDATE_GITHUB_RELEASES_URL, 403, "rate limited", {}, None))
    with pytest.raises(UpdateCheckError):
        fetch_latest_release()


def test_fetch_network_error_raises(capture_urlopen) -> None:
    capture_urlopen(urllib.error.URLError("connection refused"))
    with pytest.raises(UpdateCheckError):
        fetch_latest_release()


def test_fetch_invalid_json_raises(capture_urlopen) -> None:
    capture_urlopen("not json at all")
    with pytest.raises(UpdateCheckError):
        fetch_latest_release()


def test_fetch_non_dict_payload_raises(capture_urlopen) -> None:
    capture_urlopen(json.dumps([1, 2, 3]))
    with pytest.raises(UpdateCheckError):
        fetch_latest_release()


def test_fetch_missing_tag_name_raises(capture_urlopen) -> None:
    capture_urlopen(json.dumps({"name": "no tag here"}))
    with pytest.raises(UpdateCheckError):
        fetch_latest_release()


# --------------------------------------------------------------------------- #
# ui.update_worker 信号路由
# --------------------------------------------------------------------------- #
def test_worker_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        update_client.urllib.request,
        "urlopen",
        lambda request, timeout=None: _FakeResponse(_RELEASE_ENVELOPE),
    )
    worker = UpdateCheckWorker(timeout_s=1.0)
    results: list[object] = []
    worker.signals.succeeded.connect(results.append)

    worker.run()  # 直接调用（不起线程），验证信号路由

    assert isinstance(results[0], ReleaseInfo)
    assert results[0].tag_name == "v9.9.9"


def test_worker_failure_emits_failed_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(request, timeout=None):
        raise urllib.error.URLError("down")

    monkeypatch.setattr(update_client.urllib.request, "urlopen", _boom)
    worker = UpdateCheckWorker(timeout_s=1.0)
    failures: list[str] = []
    worker.signals.failed.connect(failures.append)

    worker.run()

    assert len(failures) == 1
    assert "down" in failures[0]
