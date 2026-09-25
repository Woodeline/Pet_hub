"""core.config —— 应用配置：``AppConfig`` dataclass + ``ConfigStore`` JSON 读写。

**本模块禁止 import 任何图形界面（Qt/GUI）库。**

容错是硬要求（FR-39 / 架构 §9.6）：
- 文件缺失 / JSON 解析失败 / 字段类型错误 / 越界值 → **逐字段** 回落默认值，绝不抛异常崩溃。
- 保存采用「写临时文件 + ``os.replace`` 原子替换」，避免半写损坏。
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

from desktop_pet.core import constants as C

logger = logging.getLogger(__name__)

#: ``scale`` 允许的容差（浮点比较）
_SCALE_EPSILON: Final[float] = 1e-6


def _coerce_int(value: Any, default: int) -> int:
    """把任意值安全转换为 int；bool 视为非法（避免 True→1 的语义混淆）。"""

    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        # 仅当是整数值的浮点才接受
        return int(value) if float(value).is_integer() else default
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (ValueError, TypeError):
            return default
    return default


def _coerce_float(value: Any, default: float) -> float:
    """把任意值安全转换为 float。"""

    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (ValueError, TypeError):
            return default
    return default


def _coerce_bool(value: Any, default: bool) -> bool:
    """把任意值安全转换为 bool；字符串仅接受常见真/假字面量。"""

    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in ("true", "1", "yes", "on"):
            return True
        if normalized in ("false", "0", "no", "off"):
            return False
    return default


def _coerce_scale(value: Any, default: float) -> float:
    """把缩放值收敛到 ``SCALES`` 允许档位；非法值回落默认。"""

    candidate = _coerce_float(value, default)
    for allowed in C.SCALES:
        if abs(candidate - allowed) < _SCALE_EPSILON:
            return float(allowed)
    return float(default)


def _coerce_level(value: Any, default: str) -> str:
    """把日语难度值收敛到 ``JP_LEVELS`` 内的合法等级；非法值回落默认。"""

    if isinstance(value, str):
        candidate = value.strip()
        if candidate in C.JP_LEVELS:
            return candidate
    return default


def _coerce_theme(value: Any, default: str) -> str:
    """把主题值收敛到白名单 ``THEME_ALLOWED``；非字符串 / 空串 / 非法值一律回落默认。

    照 :func:`_coerce_level` 先例做**取值**校验（而非仅类型校验的 :func:`_coerce_str`）：
    ``"banana"`` 这类“合法类型、非法取值”的字符串会原样通过 str 校验，随后在渲染器
    ``THEMES["banana"]`` 处 ``KeyError``，违背 FR-39「越界值逐字段回落、绝不崩溃」。
    """

    if isinstance(value, str):
        candidate = value.strip()
        if candidate in C.THEME_ALLOWED:
            return candidate
    return default


def _coerce_skin_name(value: Any, default: str) -> str:
    """皮肤包名：非字符串回默认；空串是合法值（= 自动选择）。

    不做包名白名单校验 —— 包由用户在 ``skins/`` 自行投放；不存在的包名由
    渲染层回落自动选择（:func:`build_skin_renderer`），此处只保证类型安全。
    """

    if isinstance(value, str):
        return value.strip()
    return default


def _coerce_duration(value: Any, default: int) -> int:
    """把学习泡泡时长收敛到档位 ``JP_BUBBLE_DURATION_OPTIONS``；非法值回落默认。"""

    candidate = _coerce_int(value, default)
    if candidate in C.JP_BUBBLE_DURATION_OPTIONS:
        return candidate
    return int(default)


def _coerce_daily_limit(value: Any, default: int) -> int:
    """把每日上限收敛到档位 ``JP_DAILY_LIMIT_OPTIONS``；非法值回落默认。"""

    candidate = _coerce_int(value, default)
    if candidate in C.JP_DAILY_LIMIT_OPTIONS:
        return candidate
    return int(default)


def _coerce_str(value: Any, default: str, allow_empty: bool = True) -> str:
    """把任意值安全转换为字符串。

    Args:
        value: 待转换的原始值。
        default: 非法 / 空（且不允许空）时回落的默认值。
        allow_empty: ``True``（默认）时允许返回空串；``False`` 时空串回落默认值。

    Returns:
        去除首尾空白后的字符串；``value`` 非字符串时回落默认值。
    """

    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text and not allow_empty:
        return default
    return text


@dataclass
class AppConfig:
    """应用配置数据载体（架构 §9.6 schema）。

    Attributes:
        version: schema 版本号，便于未来迁移。
        window_x: 窗口左上角 x（``-1`` 表示自动定位到主屏右下角）。
        window_y: 窗口左上角 y（``-1`` 表示自动定位到主屏右下角）。
        scale: 缩放档位，取值 ``0.8 / 1.0 / 1.2``。
        listen_enabled: 全局键盘监听开关。
        bubble_enabled: 气泡提示开关（PRD Q-01 的"静音"含义）。
        autostart: 开机自启开关。
        reduce_motion: 减少动效（对应 prefers-reduced-motion），默认 ``False``。
        theme: 主题皮肤（``default`` / 四季 / 节日 / ``auto``），默认 ``default``。
        jp_enabled: 日语学习开关（JP-02，默认关闭）。
        jp_level: 日语难度等级（JP-06，默认 ``N5``，取值 ``N5..N1``）。
        jp_bubble_duration_s: 学习泡泡停留时长（秒，默认 30，取值 15/30/60）。
        jp_daily_limit: 每日展示上限（默认 15，取值 5/10/15/20/30）。
        deepseek_api_key: DeepSeek API Key（默认空 ⇒ 直接离线降级，不发请求）。
        deepseek_base_url: DeepSeek OpenAI 兼容接口地址（默认 ``LLM_ENDPOINT``）。
        deepseek_model: 模型名（默认 ``deepseek-chat``）。
        word_detail_llm_timeout_s: 联网超时（秒，默认 10.0）。
        word_detail_llm_retries: 网络类失败重试次数（默认 1）。
    """

    version: int = C.CONFIG_VERSION
    window_x: int = C.DEFAULT_WINDOW_X
    window_y: int = C.DEFAULT_WINDOW_Y
    scale: float = C.DEFAULT_SCALE
    listen_enabled: bool = True
    bubble_enabled: bool = True
    autostart: bool = False
    reduce_motion: bool = False
    theme: str = C.DEFAULT_THEME
    skin_name: str = C.DEFAULT_SKIN_NAME
    jp_enabled: bool = False
    jp_level: str = C.JP_DEFAULT_LEVEL
    jp_bubble_duration_s: int = C.JP_BUBBLE_DURATION_S
    jp_daily_limit: int = C.JP_DAILY_LIMIT
    deepseek_api_key: str = ""
    deepseek_base_url: str = C.LLM_ENDPOINT
    deepseek_model: str = C.LLM_MODEL
    word_detail_llm_timeout_s: float = C.LLM_TIMEOUT_S
    word_detail_llm_retries: int = C.LLM_RETRIES

    def to_dict(self) -> dict[str, Any]:
        """序列化为可 JSON 化的字典。"""

        return {
            "version": int(self.version),
            "window_x": int(self.window_x),
            "window_y": int(self.window_y),
            "scale": float(self.scale),
            "listen_enabled": bool(self.listen_enabled),
            "bubble_enabled": bool(self.bubble_enabled),
            "autostart": bool(self.autostart),
            "reduce_motion": bool(self.reduce_motion),
            "theme": str(self.theme),
            "skin_name": str(self.skin_name),
            "jp_enabled": bool(self.jp_enabled),
            "jp_level": str(self.jp_level),
            "jp_bubble_duration_s": int(self.jp_bubble_duration_s),
            "jp_daily_limit": int(self.jp_daily_limit),
            "deepseek_api_key": str(self.deepseek_api_key),
            "deepseek_base_url": str(self.deepseek_base_url),
            "deepseek_model": str(self.deepseek_model),
            "word_detail_llm_timeout_s": float(self.word_detail_llm_timeout_s),
            "word_detail_llm_retries": int(self.word_detail_llm_retries),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        """从字典**逐字段容错**构造配置。

        缺失字段、类型错误、越界值一律回落默认值，绝不抛异常。
        """

        defaults = cls()
        if not isinstance(data, dict):
            logger.warning("配置数据不是 dict（type=%s），全部使用默认值", type(data).__name__)
            return defaults

        def get(key: str) -> Any:
            return data.get(key, None)

        return cls(
            version=_coerce_int(get("version"), defaults.version),
            window_x=_coerce_int(get("window_x"), defaults.window_x),
            window_y=_coerce_int(get("window_y"), defaults.window_y),
            scale=_coerce_scale(get("scale"), defaults.scale),
            listen_enabled=_coerce_bool(get("listen_enabled"), defaults.listen_enabled),
            bubble_enabled=_coerce_bool(get("bubble_enabled"), defaults.bubble_enabled),
            autostart=_coerce_bool(get("autostart"), defaults.autostart),
            reduce_motion=_coerce_bool(get("reduce_motion"), defaults.reduce_motion),
            theme=_coerce_theme(get("theme"), defaults.theme),
            # 包名是用户投放的任意目录名，不做白名单（仅类型/空值校验）；
            # 不存在的包由 build_skin_renderer 回落自动选择，不弹错误。
            skin_name=_coerce_skin_name(get("skin_name"), defaults.skin_name),
            jp_enabled=_coerce_bool(get("jp_enabled"), defaults.jp_enabled),
            jp_level=_coerce_level(get("jp_level"), defaults.jp_level),
            jp_bubble_duration_s=_coerce_duration(
                get("jp_bubble_duration_s"), defaults.jp_bubble_duration_s
            ),
            jp_daily_limit=_coerce_daily_limit(get("jp_daily_limit"), defaults.jp_daily_limit),
            deepseek_api_key=_coerce_str(
                get("deepseek_api_key"), defaults.deepseek_api_key, allow_empty=True
            ),
            deepseek_base_url=_coerce_str(
                get("deepseek_base_url"), defaults.deepseek_base_url, allow_empty=False
            ),
            deepseek_model=_coerce_str(
                get("deepseek_model"), defaults.deepseek_model, allow_empty=False
            ),
            word_detail_llm_timeout_s=_coerce_float(
                get("word_detail_llm_timeout_s"), defaults.word_detail_llm_timeout_s
            ),
            word_detail_llm_retries=_coerce_int(
                get("word_detail_llm_retries"), defaults.word_detail_llm_retries
            ),
        )


class ConfigStore:
    """负责 ``config.json`` 的容错读取与原子保存。"""

    def __init__(self, path: Path) -> None:
        """创建配置存储。

        Args:
            path: 配置文件绝对路径。
        """

        self._path: Path = Path(path)

    @property
    def path(self) -> Path:
        """配置文件路径。"""

        return self._path

    @staticmethod
    def default_path() -> Path:
        """返回默认配置文件路径 ``%APPDATA%\\desktop-pet\\config.json``。

        当 ``APPDATA`` 不可用时回落到用户主目录，保证任何环境下都能返回一个可写路径。
        """

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.CONFIG_FILE_NAME

    @staticmethod
    def log_path() -> Path:
        """返回默认日志文件路径 ``%APPDATA%\\desktop-pet\\app.log``。"""

        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else Path.home()
        return base / C.CONFIG_DIR_NAME / C.LOG_FILE_NAME

    def _read_raw(self) -> dict[str, Any]:
        """读取并解析原始 JSON。

        任何异常（文件缺失 / 权限 / 解析失败 / 非对象根）都被捕获，
        返回空字典以触发全默认回落（FR-39）。
        """

        try:
            if not self._path.exists():
                return {}
            text = self._path.read_text(encoding="utf-8")
            if not text.strip():
                logger.warning("配置文件为空：%s，使用默认值", self._path)
                return {}
            data = json.loads(text)
            if not isinstance(data, dict):
                logger.warning("配置根节点不是对象：%s，使用默认值", self._path)
                return {}
            return data
        except json.JSONDecodeError as exc:
            logger.warning("配置文件 JSON 解析失败（%s）：%s，使用默认值", self._path, exc)
        except OSError as exc:
            logger.warning("读取配置文件失败（%s）：%s，使用默认值", self._path, exc)
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("读取配置时发生未预期异常（%s），使用默认值", self._path)
        return {}

    def load(self) -> AppConfig:
        """加载配置；任何异常/损坏都回落默认值，永不为抛异常设计。"""

        raw = self._read_raw()
        try:
            cfg = AppConfig.from_dict(raw)
            logger.info("配置加载完成：%s", cfg.to_dict())
            return cfg
        except Exception:  # noqa: BLE001
            logger.exception("构造配置对象失败（%s），使用全默认值", self._path)
            return AppConfig()

    def save(self, cfg: AppConfig) -> None:
        """原子保存配置（写临时文件 → ``os.replace``）。

        失败仅记 warning，不抛出（避免阻塞退出流程）。
        """

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = json.dumps(cfg.to_dict(), ensure_ascii=False, indent=2)
            fd, tmp_name = tempfile.mkstemp(
                prefix="config-", suffix=".tmp", dir=str(self._path.parent)
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_name, self._path)
            except Exception:
                # 清理残留临时文件后继续抛出到外层统一处理
                try:
                    if os.path.exists(tmp_name):
                        os.remove(tmp_name)
                except OSError:
                    pass
                raise
            logger.info("配置已保存：%s", cfg.to_dict())
        except Exception:  # noqa: BLE001 —— 边界处绝不冒泡崩溃
            logger.exception("保存配置失败（%s），忽略本次保存", self._path)


__all__ = ["AppConfig", "ConfigStore"]
