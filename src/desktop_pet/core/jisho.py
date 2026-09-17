"""core.jisho —— Jisho 词典纯同步查询（零 Qt、零 ``time`` / ``datetime``）。

设计要点（架构 §B8 / A3.1）：
- 联网只用标准库 ``urllib.request`` + ``urllib.parse.quote`` + ``json``，超时默认 5s，
  **不开线程、不 import Qt、不 import time/datetime**（线程边界在 ``ui`` / ``app`` 层）。
- ``parse`` 取响应 ``data[0]``，无结果返回 ``None``；``fetch`` 把 ``None`` 转成
  :class:`JishoNotFound`，其余网络 / 解析错误统一转 :class:`JishoError`。
- 只做英文释义解析，不做机器翻译；本地中文与 Jisho 英文并存展示（来源标注）。
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)


class JishoError(Exception):
    """Jisho 查询失败（网络错误 / HTTP 错误 / JSON 解析失败等）。"""


class JishoNotFound(JishoError):
    """Jisho 查询成功但无结果（响应中无 ``data[0]``）。"""


@dataclass(frozen=True)
class JishoResult:
    """一条 Jisho 查询结果（只读，含读音 / 词性 / 英文释义 / JLPT / 常见标记）。"""

    word: str
    readings: tuple[str, ...]
    parts_of_speech: tuple[str, ...]
    english_definitions: tuple[str, ...]
    jlpt: tuple[str, ...]
    is_common: bool

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {
            "word": self.word,
            "readings": list(self.readings),
            "parts_of_speech": list(self.parts_of_speech),
            "english_definitions": list(self.english_definitions),
            "jlpt": list(self.jlpt),
            "is_common": bool(self.is_common),
        }

    @classmethod
    def from_dict(cls, data: Any) -> "JishoResult | None":
        """逐字段容错构造结果；``word`` 缺失/非字符串则返回 ``None``。"""

        if not isinstance(data, dict):
            return None
        raw_word = data.get("word")
        if not isinstance(raw_word, str) or not raw_word.strip():
            return None
        is_common_raw = data.get("is_common")
        return cls(
            word=raw_word.strip(),
            readings=_as_str_tuple(data.get("readings")),
            parts_of_speech=_as_str_tuple(data.get("parts_of_speech")),
            english_definitions=_as_str_tuple(data.get("english_definitions")),
            jlpt=_as_str_tuple(data.get("jlpt")),
            is_common=bool(is_common_raw) if isinstance(is_common_raw, bool) else False,
        )


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    """把列表安全转换为去空白、去重的字符串元组；非法输入返回空元组。"""

    if not isinstance(value, list):
        return ()
    result: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip() and item.strip() not in result:
            result.append(item.strip())
    return tuple(result)


def build_url(keyword: str) -> str:
    """构造 Jisho 查询 URL（对词条做 URL 编码）。"""

    return f"{C.JISHO_API_URL}?keyword={urllib.parse.quote(keyword)}"


def fetch(keyword: str, timeout_s: float = C.JISHO_TIMEOUT_S) -> JishoResult:
    """同步查询 Jisho 并返回解析结果。

    Args:
        keyword: 待查询词条（非空字符串）。
        timeout_s: 网络超时秒数。

    Returns:
        :class:`JishoResult`。

    Raises:
        JishoNotFound: 查询成功但无结果。
        JishoError: 网络 / HTTP / JSON 解析等其它失败。
    """

    normalized = (keyword or "").strip()
    if not normalized:
        raise JishoError("查询词为空")

    url = build_url(normalized)
    logger.info("查询 Jisho：%s", normalized)
    try:
        request = urllib.request.Request(
            url, headers={"User-Agent": "desktop-pet/1.0 (Japanese word lookup)"}
        )
        with urllib.request.urlopen(request, timeout=timeout_s) as response:  # noqa: S310
            raw = response.read().decode("utf-8")
        payload = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise JishoError(f"查询 Jisho 失败：{exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as exc:
        raise JishoError(f"解析 Jisho 响应失败：{exc}") from exc

    result = parse(payload)
    if result is None:
        raise JishoNotFound(f"未找到该词：{normalized}")
    return result


def parse(payload: Any) -> JishoResult | None:
    """从 Jisho 响应体解析第一条结果；无结果或结构非法返回 ``None``。"""

    if not isinstance(payload, dict):
        return None
    data = payload.get("data")
    if not isinstance(data, list) or not data:
        return None
    first = data[0]
    if not isinstance(first, dict):
        return None
    return _parse_entry(first)


def _parse_entry(entry: dict[str, Any]) -> JishoResult | None:
    """解析单条 Jisho 词条；无法取得 ``word`` 时返回 ``None``。"""

    japanese = entry.get("japanese")
    readings: list[str] = []
    word = ""
    if isinstance(japanese, list):
        for jp in japanese:
            if not isinstance(jp, dict):
                continue
            reading = jp.get("reading")
            if isinstance(reading, str) and reading.strip() and reading.strip() not in readings:
                readings.append(reading.strip())
            if not word:
                candidate = jp.get("word")
                if isinstance(candidate, str) and candidate.strip():
                    word = candidate.strip()

    if not word:
        slug = entry.get("slug")
        word = slug.strip() if isinstance(slug, str) and slug.strip() else ""

    if not word:
        return None

    senses = entry.get("senses")
    parts: list[str] = []
    definitions: list[str] = []
    if isinstance(senses, list):
        for sense in senses:
            if not isinstance(sense, dict):
                continue
            pos_list = sense.get("parts_of_speech")
            if isinstance(pos_list, list):
                for pos in pos_list:
                    if isinstance(pos, str) and pos.strip() and pos.strip() not in parts:
                        parts.append(pos.strip())
            eng_list = sense.get("english_definitions")
            if isinstance(eng_list, list):
                for eng in eng_list:
                    if isinstance(eng, str) and eng.strip():
                        definitions.append(eng.strip())
                        if len(definitions) >= C.JISHO_MAX_DEFINITIONS:
                            break
            if len(definitions) >= C.JISHO_MAX_DEFINITIONS:
                break

    jlpt: list[str] = []
    jlpt_list = entry.get("jlpt")
    if isinstance(jlpt_list, list):
        for level in jlpt_list:
            if isinstance(level, str) and level.strip() and level.strip() not in jlpt:
                jlpt.append(level.strip())

    is_common_raw = entry.get("is_common")
    is_common = bool(is_common_raw) if isinstance(is_common_raw, bool) else False

    return JishoResult(
        word=word,
        readings=tuple(readings),
        parts_of_speech=tuple(parts),
        english_definitions=tuple(definitions),
        jlpt=tuple(jlpt),
        is_common=is_common,
    )


__all__ = ["JishoResult", "JishoError", "JishoNotFound", "build_url", "fetch", "parse"]
