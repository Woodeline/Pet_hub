"""core.tts_client —— 日语单词发音联网客户端（纯同步，零 Qt 零 time）。

**本模块禁止 import 任何图形界面（Qt/GUI）库，亦不得调用 ``time`` / ``datetime``；
联网只用标准库 ``urllib.request``（不引入 requests/httpx）；不开线程**
（线程边界在 ``ui`` 层 ``QThreadPool``，与 :mod:`desktop_pet.core.llm_client` 同范式）。

**多源回退**（2026-10-01 实测定参）：`translate.google.com` 在国内网络不可达
（`urlopen timed out`），故按序尝试：
1. 有道词典发音 ``dict.youdao.com/dictvoice?audio=<text>&le=ja``（国内可达，
   返回 ``audio/mpeg``，实测无需鉴权；本机验证 open/play 均成功）；
2. Google 翻译 TTS ``translate.google.com/translate_tts?...&tl=ja``（海外回退；
   **缺失 User-Agent 会被 403**，必须携带浏览器 UA）。
一个源网络失败/响应非法 → 尝试下一个；全部失败抛最后一个异常。
限流靠调用方磁盘缓存（:mod:`desktop_pet.core.audio_cache`）挡重复请求。

**发音输入优先假名**（纠错机制）：日语汉字的不规则读法（熟字训如 明後日=あさって）
TTS 按字面拼读必错；假名即读音，优先喂假名，词头仅在假名缺失/含脏字符时兜底。

异常分类：
- :class:`TTSConfigError`：发音文本为空（直接失败，不发请求）。
- :class:`TTSNetworkError`：``URLError`` / ``TimeoutError`` / ``OSError`` / 非 200。
- :class:`TTSParseError`：响应非 audio、或正文过短（视为非法）。
"""

from __future__ import annotations

import logging
import urllib.error
import urllib.parse
import urllib.request

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)

#: 缺失 UA 会被 Google 源 403，统一携带常见浏览器 UA（有道源不敏感）。
_TTS_USER_AGENT: str = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
#: 合法 MP3 至少几百字节；更短视为错误页 / 空响应。
_MIN_AUDIO_BYTES: int = 512

_YOUDAO_BASE: str = "https://dict.youdao.com/dictvoice"
_GOOGLE_BASE: str = "https://translate.google.com/translate_tts"


# --------------------------------------------------------------------------- #
# 异常族
# --------------------------------------------------------------------------- #
class TTSError(Exception):
    """获取发音失败的基类。"""


class TTSConfigError(TTSError):
    """配置缺失（发音文本为空）。"""


class TTSNetworkError(TTSError):
    """网络 / 超时 / 其它 HTTP 错误。"""


class TTSParseError(TTSError):
    """响应非法（非 audio / 正文过短）。"""


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #
def _is_pure_kana(text: str) -> bool:
    """判断文本是否只含平假名/片假名（含长音 ``ー``、中点 ``・``）。

    用于发音输入的**数据卫生防线**：假名字段是读音真相，但若混入拉丁字母 /
    汉字 / 数字等脏数据，喂给 TTS 同样会读错，此时宁可信词头。
    """

    if not text:
        return False
    return all(
        "\u3040" <= ch <= "\u30ff" or ch in "ー・"
        for ch in text
    )


def spoken_text(word: str, kana: str) -> str:
    """返回用于发音的文本：**优先假名**，词头兜底；均空返回空串。

    纠错机制（2026-10-01「明後日」案例）：日语汉字常有不规则读法
    （明後日=あさって 熟字训），TTS 按字面拼读汉字必错；假名即读音本身，
    喂假名永不出错。仅当假名缺失**或假名字段混入非假名字符**（数据脏）
    时才回落词头表记。
    """

    kana_text = str(kana or "").strip()
    word_text = str(word or "").strip()
    if _is_pure_kana(kana_text):
        return kana_text
    return word_text or kana_text


def _youdao_url(text: str) -> str:
    """有道词典发音 URL（``le=ja`` 日语）。"""

    return f"{_YOUDAO_BASE}?{urllib.parse.urlencode({'audio': text, 'le': C.TTS_LANG})}"


def _google_url(text: str) -> str:
    """Google 翻译 TTS URL（``tl=ja`` 日语，非官方 ``client=tw-ob`` 通道）。"""

    return (
        f"{_GOOGLE_BASE}?"
        + urllib.parse.urlencode(
            {"ie": "UTF-8", "client": "tw-ob", "tl": C.TTS_LANG, "q": text}
        )
    )


#: 源优先级：有道（国内可达）在前，Google（海外回退）在后。
_TTS_SOURCES: tuple[tuple[str, object], ...] = (
    ("youdao", _youdao_url),
    ("google", _google_url),
)


# --------------------------------------------------------------------------- #
# 客户端
# --------------------------------------------------------------------------- #
class TTSClient:
    """同步抓取一段日语发音 MP3（多源按序回退，成功返回原始字节）。"""

    def __init__(self, timeout_s: float = 6.0) -> None:
        """构造客户端。

        Args:
            timeout_s: 单源单次请求超时秒数（两源全超时的最坏等待 ≈ 2 倍）。
        """

        self._timeout_s: float = float(timeout_s)

    def fetch(self, word: str, kana: str) -> bytes:
        """抓取 ``word``（缺省回落 ``kana``）的日语发音 MP3 字节。

        Raises:
            TTSConfigError: 发音文本为空。
            TTSNetworkError: 全部源网络失败（抛最后一个）。
            TTSParseError: 全部源响应非法（抛最后一个）。
        """

        text = spoken_text(word, kana)
        if not text:
            raise TTSConfigError("发音文本为空")

        last_error: TTSError | None = None
        for name, builder in _TTS_SOURCES:
            url = builder(text)  # type: ignore[operator]
            try:
                return self._fetch_url(url)
            except (TTSNetworkError, TTSParseError) as exc:
                last_error = exc
                logger.info("发音源 %s 失败：%s", name, exc)
        assert last_error is not None  # 源列表非空，必有失败
        raise last_error

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _fetch_url(self, url: str) -> bytes:
        """请求单个源 URL 并校验响应（网络/解析失败抛对应异常）。"""

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": _TTS_USER_AGENT,
                "Referer": "https://dict.youdao.com/",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as resp:
                status = int(getattr(resp, "status", 200))
                content_type = str(resp.headers.get("Content-Type", ""))
                data = resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise TTSNetworkError(f"发音请求失败：{exc}") from exc
        if status != 200:
            raise TTSNetworkError(f"发音请求失败（HTTP {status}）")
        if "audio" not in content_type.lower():
            raise TTSParseError(f"发音响应不是音频（{content_type or '无类型'}）")
        if len(data) < _MIN_AUDIO_BYTES:
            raise TTSParseError("发音响应正文过短")
        return data


#: 兼容别名（一期仅实现 Google 源时的旧名）。
GoogleTTSClient = TTSClient


__all__ = [
    "TTSClient",
    "GoogleTTSClient",
    "TTSError",
    "TTSConfigError",
    "TTSNetworkError",
    "TTSParseError",
    "spoken_text",
]
