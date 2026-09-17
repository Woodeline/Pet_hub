"""core.llm_client —— DeepSeek（OpenAI 兼容）中文详情联网客户端（纯同步，零 Qt 零 time）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``；
联网只用标准库 ``urllib.request`` + ``json``（不引入 requests/httpx）；不开线程**
（线程边界在 ``ui`` 层 ``QThreadPool``）。

异常分类：
- :class:`LLMConfigError`：空 API Key 等配置缺失（直接离线降级，不发请求）。
- :class:`LLMAuthError`：HTTP 401 / 403。
- :class:`LLMNetworkError`：``URLError`` / ``TimeoutError`` / ``OSError`` / 其它 HTTP 错误。
- :class:`LLMParseError`：JSON 解码失败 / 结构非法 / 五字段全空。

严格 JSON 提取（:meth:`DeepSeekClient._extract_json`）容错：
剥离 ```json 围栏 → 取首个 ``{`` 到匹配 ``}`` → ``json.loads``；亦兼容
OpenAI 兼容响应信封（``choices[0].message.content``）。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any

from desktop_pet.core import constants as C
from desktop_pet.core.word_detail import WordDetail

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 异常族
# --------------------------------------------------------------------------- #
class LLMError(Exception):
    """联网查询详情失败的基类。"""


class LLMAuthError(LLMError):
    """鉴权失败（HTTP 401 / 403）。"""


class LLMNetworkError(LLMError):
    """网络 / 超时 / 其它 HTTP 错误。"""


class LLMParseError(LLMError):
    """响应 JSON 解析失败 / 结构非法 / 五字段全空。"""


class LLMConfigError(LLMError):
    """配置缺失（如空 API Key）。"""


# --------------------------------------------------------------------------- #
# JSON 提取工具（模块级纯函数）
# --------------------------------------------------------------------------- #
def _try_loads_dict(text: str) -> dict[str, Any] | None:
    """尝试把字符串整体解析为 ``dict``；失败或非对象返回 ``None``。"""

    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, ValueError, TypeError):
        return None
    return obj if isinstance(obj, dict) else None


def _first_json_object(text: str) -> str | None:
    """从文本中截取**首个** ``{`` 到**匹配** ``}`` 的子串（跳过字符串字面量内的括号）。

    未找到配对的 ``}``（如被截断）返回 ``None``。
    """

    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
        elif char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    return None


def _content_from_envelope(obj: dict[str, Any]) -> str | None:
    """若 ``obj`` 是 OpenAI 兼容响应信封，返回 ``choices[0].message.content``。"""

    choices = obj.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, dict):
        return None
    message = first.get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content
    return None


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
class DeepSeekClient:
    """DeepSeek OpenAI 兼容接口的同步客户端（每次查询一次 POST）。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = C.LLM_ENDPOINT,
        model: str = C.LLM_MODEL,
        timeout_s: float = C.LLM_TIMEOUT_S,
        retries: int = C.LLM_RETRIES,
    ) -> None:
        """构造客户端。

        Args:
            api_key: API Key（空 → 调用 :meth:`fetch_word_detail` 抛 :class:`LLMConfigError`）。
            base_url: 接口地址（空 → 回落 :data:`C.LLM_ENDPOINT`）。
            model: 模型名（空 → 回落 :data:`C.LLM_MODEL`）。
            timeout_s: 单次请求超时（秒）。
            retries: 网络类失败的重试次数（仅针对网络 / 超时；鉴权不重试）。
        """

        self._api_key: str = (api_key or "").strip()
        self._base_url: str = (base_url or "").strip() or C.LLM_ENDPOINT
        self._model: str = (model or "").strip() or C.LLM_MODEL
        self._timeout_s: float = float(timeout_s)
        self._retries: int = max(0, int(retries))

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def fetch_word_detail(
        self,
        word: str,
        kana: str = "",
        level: str = "",
        translation: str = "",
    ) -> WordDetail:
        """查询并返回某词的中文五要素详情。

        Args:
            word: 日语单词（非空）。
            kana: 假名读音（可空）。
            level: JLPT 等级（可空）。
            translation: 参考中文词义（可空）。

        Returns:
            :class:`WordDetail`。

        Raises:
            LLMConfigError: 未配置 API Key 或词条为空。
            LLMAuthError: 鉴权失败。
            LLMNetworkError: 网络 / 超时 / 其它 HTTP 错误。
            LLMParseError: 响应解析失败或五字段全空。
        """

        if not self._api_key:
            raise LLMConfigError("未配置 DeepSeek API Key")
        normalized = (word or "").strip()
        if not normalized:
            raise LLMConfigError("查询词为空")

        messages = self.build_prompt(normalized, kana, level, translation)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": C.LLM_TEMPERATURE,
            "response_format": {"type": C.LLM_RESPONSE_FORMAT_TYPE},
        }

        body = self._post(payload)
        data = self._extract_json(body)
        detail = WordDetail.from_dict(data)
        if detail is None or detail.is_empty():
            raise LLMParseError("联网返回的详情为空")
        return detail

    @staticmethod
    def build_prompt(
        word: str,
        kana: str = "",
        level: str = "",
        translation: str = "",
    ) -> list[dict[str, str]]:
        """构造发给模型的对话消息（system + user），要求严格 JSON、纯中文。"""

        user_content = C.LLM_PROMPT_USER_TEMPLATE.format(
            word=str(word),
            kana=str(kana) if kana else C.WORD_DETAIL_NO_VALUE,
            level=str(level) if level else C.WORD_DETAIL_NO_VALUE,
            translation=str(translation) if translation else C.WORD_DETAIL_NO_VALUE,
        )
        return [
            {"role": "system", "content": C.LLM_PROMPT_SYSTEM},
            {"role": "user", "content": user_content},
        ]

    # ------------------------------------------------------------------ #
    # 内部：HTTP
    # ------------------------------------------------------------------ #
    def _post(self, payload: dict[str, Any]) -> str:
        """执行一次带重试的 POST，返回响应体文本。

        仅对**网络 / 超时 / 其它 HTTP 错误**重试 ``self._retries`` 次；
        ``401 / 403`` 立即抛 :class:`LLMAuthError`（不重试）。
        """

        encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Authorization": f"Bearer {self._api_key}",
            "User-Agent": "desktop-pet/1.0 (Japanese word detail)",
        }
        request = urllib.request.Request(
            self._base_url, data=encoded, headers=headers, method="POST"
        )

        attempts = max(1, self._retries + 1)
        last_error: LLMError | None = None
        for _ in range(attempts):
            try:
                with urllib.request.urlopen(  # noqa: S310 —— 仅访问用户配置的固定 HTTPS 接口
                    request, timeout=self._timeout_s
                ) as response:
                    return response.read().decode("utf-8")
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise LLMAuthError(f"鉴权失败（HTTP {exc.code}）") from exc
                last_error = LLMNetworkError(f"HTTP 错误：{exc.code}")
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                last_error = LLMNetworkError(f"网络错误：{exc}")
            except Exception as exc:  # noqa: BLE001 —— 边界处统一转网络类错误
                last_error = LLMError(f"请求异常：{exc}")

        raise last_error if last_error is not None else LLMNetworkError("请求失败")

    # ------------------------------------------------------------------ #
    # 内部：解析
    # ------------------------------------------------------------------ #
    @staticmethod
    def _extract_json(text: str) -> dict[str, Any]:
        """从响应文本中严格提取一个 JSON 对象。

        容错顺序：整体解析 → 剥围栏 / 取首个 ``{...}`` → 解析；
        若结果为 OpenAI 兼容信封，则递归解析其 ``content``。
        """

        if not isinstance(text, str) or not text.strip():
            raise LLMParseError("响应体为空")
        stripped = text.strip()

        obj = _try_loads_dict(stripped)
        if obj is None:
            candidate = _first_json_object(stripped)
            if candidate is None:
                raise LLMParseError("未能在响应中找到完整的 JSON 对象")
            obj = _try_loads_dict(candidate)
        if obj is None:
            raise LLMParseError("响应 JSON 解析失败")

        content = _content_from_envelope(obj)
        if content is not None:
            return DeepSeekClient._extract_json(content)
        return obj


__all__ = [
    "LLMError",
    "LLMAuthError",
    "LLMNetworkError",
    "LLMParseError",
    "LLMConfigError",
    "DeepSeekClient",
]
