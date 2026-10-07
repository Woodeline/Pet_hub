"""core.update_client —— 检查更新客户端（GitHub Releases，纯同步 urllib）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``**
（与 ``core.llm_client`` / ``core.tts_client`` 同一范式：联网只用标准库
``urllib.request`` + ``json``，不开线程——线程边界在 ``ui`` 层 QThreadPool）。

异常族：:class:`UpdateCheckError` 统一携带用户可读原因（网络 / HTTP / 解析 /
结构非法），调用方据此通知或记日志，绝不冒泡崩溃。

版本比较：``vX.Y.Z`` 语义化三元组纯函数（:func:`parse_version` /
:func:`is_newer`），解析失败（脏 tag / 脏本地版本）一律视为「不更新」——
宁可漏报新版本，不可误报。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)


class UpdateCheckError(Exception):
    """检查更新失败（携带用户可读原因）。"""


@dataclass(frozen=True)
class ReleaseInfo:
    """最新 Release 的最小信息集。"""

    tag_name: str
    name: str
    html_url: str


def parse_version(version: str) -> tuple[int, int, int] | None:
    """解析 ``vX.Y.Z`` / ``X.Y.Z`` 为整数三元组；非法返回 ``None``。

    宽容前导 ``v`` / ``V`` 与空白；只接受**恰好三段纯数字**（本仓库发布
    约定即三位语义化版本，四位 / 带后缀的 tag 不强行猜测语义）。
    """

    text = str(version).strip().lstrip("vV")
    parts = text.split(".")
    if len(parts) != 3:
        return None
    try:
        return (int(parts[0]), int(parts[1]), int(parts[2]))
    except ValueError:
        return None


def is_newer(remote_tag: str, local_version: str) -> bool:
    """远端 tag 是否比本地版本新（任一侧解析失败 → ``False``，不误报）。"""

    remote = parse_version(remote_tag)
    local = parse_version(local_version)
    if remote is None or local is None:
        return False
    return remote > local


def fetch_latest_release(timeout_s: float = C.UPDATE_CHECK_TIMEOUT_S) -> ReleaseInfo:
    """查询 GitHub 最新 Release（同步，无重试——单次快速失败，调用方可稍后再查）。

    Returns:
        :class:`ReleaseInfo`（``tag_name`` / ``name`` / ``html_url``）。

    Raises:
        UpdateCheckError: 网络 / HTTP / JSON / 结构非法（均含用户可读原因）。
    """

    request = urllib.request.Request(
        C.UPDATE_GITHUB_RELEASES_URL,
        headers={
            "User-Agent": f"desktop-pet/{_user_version()} (update-check)",
            "Accept": "application/vnd.github+json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=float(timeout_s)) as response:
            status = getattr(response, "status", None) or response.getcode()
            if status != 200:
                raise UpdateCheckError(f"GitHub 返回 HTTP {status}")
            payload = response.read()
    except UpdateCheckError:
        raise
    except urllib.error.HTTPError as exc:
        # GitHub 匿名限额（403）等：统一转用户可读失败
        raise UpdateCheckError(f"HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise UpdateCheckError(f"网络不可达：{exc.reason}") from exc
    except (TimeoutError, OSError) as exc:
        raise UpdateCheckError(f"网络异常：{exc}") from exc

    return _parse_release_payload(payload)


def _user_version() -> str:
    """本地版本号（延迟 import 避免包初始化顺序耦合；失败回落 unknown）。"""

    try:
        from desktop_pet import __version__

        return str(__version__)
    except Exception:  # noqa: BLE001
        return "unknown"


def _parse_release_payload(payload: bytes) -> ReleaseInfo:
    """解析 GitHub Releases API 响应信封。"""

    try:
        data: Any = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateCheckError(f"响应解析失败：{exc}") from exc
    if not isinstance(data, dict):
        raise UpdateCheckError("响应结构非法（根节点不是对象）")
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not tag.strip():
        raise UpdateCheckError("响应缺少 tag_name")
    name = data.get("name")
    html_url = data.get("html_url")
    return ReleaseInfo(
        tag_name=tag.strip(),
        name=str(name) if isinstance(name, str) else "",
        html_url=str(html_url) if isinstance(html_url, str) else "",
    )


__all__ = ["ReleaseInfo", "UpdateCheckError", "parse_version", "is_newer", "fetch_latest_release"]
