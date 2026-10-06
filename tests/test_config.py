"""配置容错测试（FR-36/37/38/39，架构 §9.6）。

**隔离要求**：所有读写都使用 ``tmp_path``，绝不触碰真实 ``%APPDATA%``。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.config import AppConfig, ConfigStore


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


# --------------------------------------------------------------------------- #
# 1. 损坏 / 非法输入 → 逐字段回落默认且不抛异常（FR-39）
# --------------------------------------------------------------------------- #
def test_missing_file_uses_defaults(config_store: ConfigStore) -> None:
    cfg = config_store.load()
    assert cfg == AppConfig()


def test_empty_file_uses_defaults(config_store: ConfigStore, config_path: Path) -> None:
    _write(config_path, "")
    assert config_store.load() == AppConfig()


def test_whitespace_file_uses_defaults(config_store: ConfigStore, config_path: Path) -> None:
    _write(config_path, "   \n\t  ")
    assert config_store.load() == AppConfig()


def test_invalid_json_uses_defaults(config_store: ConfigStore, config_path: Path) -> None:
    _write(config_path, "{ this is not json ]")
    assert config_store.load() == AppConfig()


@pytest.mark.parametrize("payload", ["[1, 2, 3]", '"just a string"', "42", "true", "null"])
def test_non_object_root_uses_defaults(
    config_store: ConfigStore, config_path: Path, payload: str
) -> None:
    _write(config_path, payload)
    assert config_store.load() == AppConfig()


def test_path_is_directory_uses_defaults(tmp_path: Path) -> None:
    directory = tmp_path / "config.json"
    directory.mkdir()
    store = ConfigStore(directory)  # 指向目录而非文件
    assert store.load() == AppConfig()


# --------------------------------------------------------------------------- #
# 2. 字段类型错误 / 越界 → 该字段回落默认，其余保留
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("abc", 1.0),      # 非数字字符串
        (99, 1.0),         # 越界（不在 SCALES）
        (0.9, 1.0),        # 非法档位
        (True, 1.0),       # bool 属于非法
        (None, 1.0),
        (0.8, 0.8),        # 合法
        (1.0, 1.0),
        (1.2, 1.2),
        ("0.8", 0.8),      # 合法字符串
    ],
)
def test_scale_coercion(raw, expected) -> None:
    cfg = AppConfig.from_dict({"scale": raw})
    assert cfg.scale == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("12", 12),          # 数字字符串可解析
        ("12a", C.DEFAULT_WINDOW_X),  # 不可解析 → 默认
        (True, C.DEFAULT_WINDOW_X),   # bool 非法
        (3.5, C.DEFAULT_WINDOW_X),    # 非整数浮点非法
        (3.0, 3),                     # 整数浮点可接受
        (100, 100),
        (None, C.DEFAULT_WINDOW_X),
    ],
)
def test_int_coercion(raw, expected) -> None:
    cfg = AppConfig.from_dict({"window_x": raw})
    assert cfg.window_x == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (True, True), (False, False),
        (1, True), (0, False),
        ("true", True), ("YES", True), ("on", True),
        ("false", False), ("No", False), ("off", False),
        ("maybe", True),   # 无法识别 → 默认（listen_enabled 默认 True）
        (None, True),
    ],
)
def test_bool_coercion(raw, expected) -> None:
    cfg = AppConfig.from_dict({"listen_enabled": raw})
    assert cfg.listen_enabled == expected


def test_mixed_valid_and_invalid_fields() -> None:
    """坏字段回落默认，好字段保留。"""

    cfg = AppConfig.from_dict(
        {
            "window_x": 300,
            "scale": "oops",       # 非法 → 默认 1.0
            "listen_enabled": False,
            "bubble_enabled": "garbage",  # 非法 → 默认 True
        }
    )
    assert cfg.window_x == 300
    assert cfg.scale == 1.0
    assert cfg.listen_enabled is False
    assert cfg.bubble_enabled is True


def test_extra_fields_are_ignored() -> None:
    cfg = AppConfig.from_dict({"window_x": 5, "unknown_field": "x", "another": 123})
    assert cfg.window_x == 5
    assert cfg == AppConfig(window_x=5)


def test_missing_fields_use_defaults() -> None:
    cfg = AppConfig.from_dict({"window_y": 50})
    assert cfg.window_y == 50
    assert cfg.scale == AppConfig().scale
    assert cfg.listen_enabled is True


def test_from_dict_non_dict_returns_defaults() -> None:
    assert AppConfig.from_dict([1, 2]) == AppConfig()      # type: ignore[arg-type]
    assert AppConfig.from_dict("x") == AppConfig()          # type: ignore[arg-type]
    assert AppConfig.from_dict(None) == AppConfig()         # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# 3. 往返一致性
# --------------------------------------------------------------------------- #
def test_save_load_roundtrip(config_store: ConfigStore) -> None:
    original = AppConfig(
        version=1,
        window_x=321,
        window_y=654,
        scale=0.8,
        listen_enabled=False,
        bubble_enabled=False,
        autostart=True,
    )
    config_store.save(original)
    loaded = config_store.load()
    assert loaded == original
    assert loaded.to_dict() == original.to_dict()


def test_load_after_save_is_json_readable(config_store: ConfigStore, config_path: Path) -> None:
    config_store.save(AppConfig(window_x=7))
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["window_x"] == 7
    assert set(data) == {
        "version", "window_x", "window_y", "scale",
        "listen_enabled", "bubble_enabled", "autostart",
        # 增量改造：新增「减少动效」开关（UI 视觉升级 P2；CONFIG_VERSION 保持 1）
        "reduce_motion",
        # 增量改造：新增主题皮肤（UI 视觉升级 阶段 A；CONFIG_VERSION 保持 1）
        "theme",
        # 增量改造：新增皮肤包（MOD）选择（Aranara/Nahida 适配；CONFIG_VERSION 保持 1）
        "skin_name",
        # 增量改造：情绪气泡台词（预设包 + 自定义池；CONFIG_VERSION 保持 1）
        "bubble_text_pack", "bubble_texts_custom",
        # 增量改造：自定义池拆两组（自动触发组 / 敲击键盘组；CONFIG_VERSION 保持 1）
        "bubble_texts_custom_keyboard",
        "jp_enabled", "jp_level",
        "jp_bubble_duration_s", "jp_daily_limit",
        "jp_review_daily_limit",
        # 增量改造：错题本每日一次提醒开关（CONFIG_VERSION 保持 1）
        "weak_review_enabled",
        # 增量改造：DeepSeek 联网 / 中文详情配置（CONFIG_VERSION 保持 1）
        "deepseek_api_key", "deepseek_base_url", "deepseek_model",
        "word_detail_llm_timeout_s", "word_detail_llm_retries",
    }


# --------------------------------------------------------------------------- #
# 4. 原子保存
# --------------------------------------------------------------------------- #
def test_save_leaves_no_temp_files(config_store: ConfigStore, config_path: Path) -> None:
    config_store.save(AppConfig())
    leftover = list(config_path.parent.glob("*.tmp")) + list(config_path.parent.glob("config-*"))
    assert leftover == [], f"原子保存残留临时文件：{leftover}"


def test_save_creates_parent_directory(tmp_path: Path) -> None:
    nested = tmp_path / "a" / "b" / "c" / "config.json"
    store = ConfigStore(nested)
    store.save(AppConfig(window_x=11))
    assert nested.exists()


def test_save_overwrites_existing_file(config_store: ConfigStore) -> None:
    config_store.save(AppConfig(window_x=1))
    config_store.save(AppConfig(window_x=2))
    assert config_store.load().window_x == 2


def test_save_never_raises_on_bad_path(tmp_path: Path) -> None:
    """写入不可用路径不应抛异常（边界处吞掉并记日志）。"""

    # 让 parent 成为一个文件，阻止 mkdir
    (tmp_path / "blocker")
    bad = ConfigStore(tmp_path / "blocker" / "sub" / "config.json")
    (tmp_path / "blocker").write_text("x", encoding="utf-8")
    bad.save(AppConfig())  # 不应抛异常


# --------------------------------------------------------------------------- #
# 5. 默认路径（隔离 APPDATA）
# --------------------------------------------------------------------------- #
def test_default_path_uses_appdata(isolated_appdata: Path) -> None:
    path = ConfigStore.default_path()
    assert path == isolated_appdata / C.CONFIG_DIR_NAME / C.CONFIG_FILE_NAME


def test_log_path_uses_appdata(isolated_appdata: Path) -> None:
    path = ConfigStore.log_path()
    assert path.name == C.LOG_FILE_NAME
    assert path.parent == isolated_appdata / C.CONFIG_DIR_NAME


def test_default_path_without_appdata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPDATA", raising=False)
    path = ConfigStore.default_path()
    assert path.name == C.CONFIG_FILE_NAME
    assert Path.home() in path.parents


# --------------------------------------------------------------------------- #
# 6. schema 常量一致性（防漂移）
# --------------------------------------------------------------------------- #
def test_default_config_fields_match_architecture() -> None:
    cfg = AppConfig()
    assert cfg.version == C.CONFIG_VERSION == 1
    assert cfg.scale == C.DEFAULT_SCALE == 1.0
    assert cfg.listen_enabled is True
    assert cfg.bubble_enabled is True
    assert cfg.autostart is False
    assert cfg.window_x == C.DEFAULT_WINDOW_X
    assert cfg.window_y == C.DEFAULT_WINDOW_Y
    assert cfg.jp_bubble_duration_s == C.JP_BUBBLE_DURATION_S == 30
    assert cfg.jp_daily_limit == C.JP_DAILY_LIMIT == 15


# --------------------------------------------------------------------------- #
# 7. 日语记忆配置项容错（JP-17+）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, C.JP_BUBBLE_DURATION_S),       # 缺省 → 默认 30
        (15, 15),
        (30, 30),
        (60, 60),
        (15.0, 15),                           # 整数浮点可接受
        (30.0, 30),
        ("60", 60),                           # 整数字符串可解析
        (True, C.JP_BUBBLE_DURATION_S),       # bool 非法 → 默认
        ("oops", C.JP_BUBBLE_DURATION_S),     # 不可解析 → 默认
        ("8.5", C.JP_BUBBLE_DURATION_S),      # 非整数浮点 → 默认
        (1, C.JP_BUBBLE_DURATION_S),          # 旧值 1 不在档位 → 默认
        (2.0, C.JP_BUBBLE_DURATION_S),        # 旧值 2 不在档位 → 默认
        (45, C.JP_BUBBLE_DURATION_S),         # 旧值 45 不在档位 → 默认
        (300, C.JP_BUBBLE_DURATION_S),        # 旧值 300 不在档位 → 默认
    ],
)
def test_jp_bubble_duration_coercion(raw, expected) -> None:
    cfg = AppConfig.from_dict({"jp_bubble_duration_s": raw})
    assert cfg.jp_bubble_duration_s == expected
    assert isinstance(cfg.jp_bubble_duration_s, int)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, C.JP_DAILY_LIMIT),             # 缺省 → 默认 15
        (5, 5),
        (10, 10),
        (15, 15),
        (20, 20),
        (30, 30),
        ("20", 20),
        (30.0, 30),                           # 整数浮点可接受
        (True, C.JP_DAILY_LIMIT),             # bool 非法 → 默认
        (3.5, C.JP_DAILY_LIMIT),              # 非整数浮点非法 → 默认
        ("oops", C.JP_DAILY_LIMIT),           # 不可解析 → 默认
        (0, C.JP_DAILY_LIMIT),                # 0 不在档位 → 默认
        (-5, C.JP_DAILY_LIMIT),
        (7, C.JP_DAILY_LIMIT),                # 旧值 7 不在档位 → 默认
        (200, C.JP_DAILY_LIMIT),              # 旧值 200 不在档位 → 默认
        (99999, C.JP_DAILY_LIMIT),            # 越界 → 默认
    ],
)
def test_jp_daily_limit_coercion(raw, expected) -> None:
    cfg = AppConfig.from_dict({"jp_daily_limit": raw})
    assert cfg.jp_daily_limit == expected


@pytest.mark.parametrize(
    "raw, expected",
    [
        (10, 10),
        (20, 20),
        (30, 30),
        (50, 50),
        (-5, C.JP_REVIEW_DAILY_LIMIT),
        (7, C.JP_REVIEW_DAILY_LIMIT),         # 不在档位 → 默认
        (99999, C.JP_REVIEW_DAILY_LIMIT),     # 越界 → 默认
    ],
)
def test_jp_review_limit_coercion(raw, expected) -> None:
    cfg = AppConfig.from_dict({"jp_review_daily_limit": raw})
    assert cfg.jp_review_daily_limit == expected


def test_missing_jp_memory_fields_use_defaults() -> None:
    """旧配置缺两键 → 回落默认，不抛异常（向后兼容，CONFIG_VERSION 仍为 1）。"""

    cfg = AppConfig.from_dict({"version": 1, "jp_enabled": True, "jp_level": "N4"})
    assert cfg.jp_enabled is True
    assert cfg.jp_level == "N4"
    assert cfg.jp_bubble_duration_s == C.JP_BUBBLE_DURATION_S
    assert cfg.jp_daily_limit == C.JP_DAILY_LIMIT


# --------------------------------------------------------------------------- #
# 8. 「减少动效」开关容错（UI 视觉升级 P2；CONFIG_VERSION 保持 1）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, False),          # 缺字段 → 默认（不减少动效）
        (True, True),
        (False, False),
        ("yes", True),          # 常见真字面量
        ("ON", True),
        ("no", False),
        ("off", False),
        ("maybe", False),       # 无法识别字符串 → 默认 False
        ([1, 2], False),        # 非法类型（list）→ 默认 False
        ({"a": 1}, False),      # 非法类型（dict）→ 默认 False
        (123, True),            # 数值走 _coerce_bool 语义：非零 → True
        (0, False),
    ],
)
def test_reduce_motion_coercion(raw, expected) -> None:
    """复用既有 ``_coerce_bool`` 容错器；缺失 / 非法类型回落 False。"""

    cfg = AppConfig.from_dict({"reduce_motion": raw})
    assert cfg.reduce_motion is expected


def test_reduce_motion_default_and_roundtrip(config_store: ConfigStore) -> None:
    """默认关闭；显式开启后可往返序列化。"""

    assert AppConfig().reduce_motion is False
    config_store.save(AppConfig(reduce_motion=True))
    loaded = config_store.load()
    assert loaded.reduce_motion is True
    assert loaded.to_dict()["reduce_motion"] is True


# --------------------------------------------------------------------------- #
# 9. 主题皮肤字段容错（UI 视觉升级 阶段 A；CONFIG_VERSION 保持 1）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, "default"),        # 缺字段 → 默认
        (123, "default"),         # 非法类型 → 默认
        ("", "default"),          # 空串 → 默认
        ("banana", "default"),    # 合法类型、非法取值 → 默认（R3：必须白名单校验）
        (["autumn"], "default"),  # 非法类型（list）→ 默认
        ("autumn", "autumn"),     # 合法皮肤 → 保留
        ("auto", "auto"),         # auto 合法 → 保留
        ("spring_festival", "spring_festival"),
        ("  spring  ", "spring"), # 首尾空白被 strip
    ],
)
def test_theme_coercion(raw, expected) -> None:
    """白名单校验：非 str / 空串 / 非法值回落 ``default``；合法值保留。"""

    cfg = AppConfig.from_dict({"theme": raw})
    assert cfg.theme == expected


def test_theme_default_is_literal_default(config_store: ConfigStore) -> None:
    """默认值为字面量 ``"default"``，且可往返序列化。"""

    assert AppConfig().theme == "default"
    config_store.save(AppConfig(theme="winter"))
    loaded = config_store.load()
    assert loaded.theme == "winter"
    assert loaded.to_dict()["theme"] == "winter"


# --------------------------------------------------------------------------- #
# 4b. 皮肤包（MOD）选择：skin_name 容错与往返
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Aranara", "Aranara"),          # 包名原样保留（不做白名单）
        ("  Nahida  ", "Nahida"),        # 去首尾空白
        ("", ""),                        # 空串 = 自动选择（合法）
        ("vector", "vector"),            # 显式矢量
        (123, ""),                       # 非字符串回落默认（自动）
        (None, ""),
        (["Nahida"], ""),
    ],
)
def test_skin_name_coercion(raw, expected) -> None:
    """包名不做白名单（用户自行投放），仅类型安全；不存在由渲染层回落。"""

    cfg = AppConfig.from_dict({"skin_name": raw})
    assert cfg.skin_name == expected


def test_skin_name_default_and_roundtrip(config_store: ConfigStore) -> None:
    """默认值为空串（自动），且可往返序列化。"""

    assert AppConfig().skin_name == ""
    config_store.save(AppConfig(skin_name="Nahida"))
    loaded = config_store.load()
    assert loaded.skin_name == "Nahida"
    assert loaded.to_dict()["skin_name"] == "Nahida"


# --------------------------------------------------------------------------- #
# 4c. API Key 日志脱敏（安全红线：明文绝不进 app.log）
# --------------------------------------------------------------------------- #
_SECRET = "sk-super-secret-key-do-not-log"


def test_to_dict_redact_masks_nonempty_secret() -> None:
    """``redact=True`` 时非空密钥打码为 ``***``；其余字段不受影响。"""

    cfg = AppConfig(deepseek_api_key=_SECRET, window_x=11)
    raw = cfg.to_dict()
    red = cfg.to_dict(redact=True)
    assert raw["deepseek_api_key"] == _SECRET      # 默认不脱敏（写盘用）
    assert red["deepseek_api_key"] == "***"
    assert red["window_x"] == 11                   # 非敏感字段原样
    # 键集合一致：脱敏只改值，不删字段
    assert set(raw) == set(red)


def test_to_dict_redact_keeps_empty_secret_empty() -> None:
    """未配置（空）时保持空串，便于从日志区分「未配置」与「已配置」。"""

    red = AppConfig(deepseek_api_key="").to_dict(redact=True)
    assert red["deepseek_api_key"] == ""


def test_save_keeps_real_secret_on_disk(config_store: ConfigStore, config_path: Path) -> None:
    """脱敏只针对日志：磁盘必须存真值，否则联网兜底会失效。"""

    config_store.save(AppConfig(deepseek_api_key=_SECRET))
    data = json.loads(config_path.read_text(encoding="utf-8"))
    assert data["deepseek_api_key"] == _SECRET


def test_save_and_load_logs_never_contain_plaintext_key(
    config_store: ConfigStore, caplog: pytest.LogCaptureFixture
) -> None:
    """FR：保存与加载的 INFO 日志都不得出现明文 Key（回归防护）。"""

    with caplog.at_level(logging.INFO, logger="desktop_pet.core.config"):
        config_store.save(AppConfig(deepseek_api_key=_SECRET))
        loaded = config_store.load()

    assert loaded.deepseek_api_key == _SECRET        # 功能不受影响
    assert caplog.text                                   # 确实产生了日志
    assert _SECRET not in caplog.text                # 无明文
    assert "***" in caplog.text                      # 已打码


# --------------------------------------------------------------------------- #
# 4d. 情绪气泡台词：预设包 + 自定义池
# --------------------------------------------------------------------------- #
def test_bubble_text_pack_coercion_whitelist() -> None:
    """台词包名走白名单（照 theme 先例）：非法值回落 default。"""

    assert AppConfig.from_dict({"bubble_text_pack": "energy"}).bubble_text_pack == "energy"
    assert AppConfig.from_dict({"bubble_text_pack": "gentle"}).bubble_text_pack == "gentle"
    assert AppConfig.from_dict({"bubble_text_pack": "banana"}).bubble_text_pack == "default"
    assert AppConfig.from_dict({"bubble_text_pack": 123}).bubble_text_pack == "default"
    assert AppConfig.from_dict({"bubble_text_pack": None}).bubble_text_pack == "default"


def test_bubble_text_pack_roundtrip(config_store: ConfigStore) -> None:
    config_store.save(AppConfig(bubble_text_pack="gentle"))
    loaded = config_store.load()
    assert loaded.bubble_text_pack == "gentle"
    assert loaded.to_dict()["bubble_text_pack"] == "gentle"


@pytest.mark.parametrize(
    "raw,expected",
    [
        (["  摸摸我呀~ ", "加油鸭！", "摸摸我呀~"], ["摸摸我呀~", "加油鸭！"]),  # strip + 去重
        (["", "   ", "有效"], ["有效"]),                                        # 去空
        ([123, None, "有效"], ["有效"]),                                        # 非字符串跳过
        ([], []),                                                               # 空 = 合法（不启用）
        ("不是列表", []),                                                        # 非列表回默认
        (None, []),
    ],
)
def test_bubble_texts_custom_coercion(raw, expected) -> None:
    assert AppConfig.from_dict({"bubble_texts_custom": raw}).bubble_texts_custom == expected


def test_bubble_texts_custom_limits() -> None:
    """超长截断到 MAX_LEN；超量截断到 MAX_COUNT。"""

    long_text = "啊" * (C.BUBBLE_TEXT_CUSTOM_MAX_LEN + 10)
    cfg = AppConfig.from_dict({"bubble_texts_custom": [long_text]})
    assert len(cfg.bubble_texts_custom[0]) == C.BUBBLE_TEXT_CUSTOM_MAX_LEN

    many = [f"台词{i}" for i in range(C.BUBBLE_TEXT_CUSTOM_MAX_COUNT + 10)]
    cfg = AppConfig.from_dict({"bubble_texts_custom": many})
    assert len(cfg.bubble_texts_custom) == C.BUBBLE_TEXT_CUSTOM_MAX_COUNT


def test_bubble_texts_custom_roundtrip(config_store: ConfigStore) -> None:
    texts = ["摸摸我呀~", "加油鸭！"]
    config_store.save(AppConfig(bubble_texts_custom=texts))
    loaded = config_store.load()
    assert loaded.bubble_texts_custom == texts
    assert loaded.to_dict()["bubble_texts_custom"] == texts


# --------------------------------------------------------------------------- #
# 4b. 敲击键盘组自定义池（2026-09-26 需求 C-4）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        ([" 敲吧敲吧~ ", "键盘敲得真快！", "敲吧敲吧~"], ["敲吧敲吧~", "键盘敲得真快！"]),
        (["", "  ", "有效"], ["有效"]),
        ([123, None, "有效"], ["有效"]),
        ([], []),
        ("不是列表", []),
        (None, []),
    ],
)
def test_bubble_texts_custom_keyboard_coercion(raw, expected) -> None:
    """敲击组复用同一清洗规则（strip/去空/去重/限长）。"""

    cfg = AppConfig.from_dict({"bubble_texts_custom_keyboard": raw})
    assert cfg.bubble_texts_custom_keyboard == expected


def test_bubble_texts_custom_keyboard_does_not_filter_keyword() -> None:
    """入库**不**做键盘关键字过滤：门控发生在展示时按触发源判定，入库保留原样。

    这样才能让用户在两组之间搬移文案而不丢条目。
    """

    texts = ["键盘敲得真快！", "摸摸头~"]
    cfg = AppConfig.from_dict({"bubble_texts_custom_keyboard": texts})
    assert cfg.bubble_texts_custom_keyboard == texts


def test_bubble_texts_custom_keyboard_roundtrip(config_store: ConfigStore) -> None:
    """两组自定义池相互独立：写一组不影响另一组，落盘后可读回。"""

    auto = ["自动台词A"]
    hit = ["敲击台词B", "键盘台词C"]
    config_store.save(AppConfig(bubble_texts_custom=auto, bubble_texts_custom_keyboard=hit))
    loaded = config_store.load()
    assert loaded.bubble_texts_custom == auto
    assert loaded.bubble_texts_custom_keyboard == hit
    assert loaded.to_dict()["bubble_texts_custom_keyboard"] == hit


def test_legacy_config_without_keyboard_pool_loads_empty() -> None:
    """向后兼容：旧配置文件没有 bubble_texts_custom_keyboard 键 → 敲击组为空，不报错。"""

    cfg = AppConfig.from_dict({"bubble_texts_custom": ["旧的自动组"], "bubble_text_pack": "gentle"})
    assert cfg.bubble_texts_custom == ["旧的自动组"]
    assert cfg.bubble_texts_custom_keyboard == []
    assert cfg.bubble_text_pack == "gentle"


def test_weak_review_enabled_default_and_missing_field() -> None:
    """错题提醒开关默认开；旧配置缺该字段时同样回落默认（向后兼容）。"""

    assert AppConfig().weak_review_enabled is True
    assert AppConfig.from_dict({}).weak_review_enabled is True
    assert AppConfig.from_dict({"weak_review_enabled": "no"}).weak_review_enabled is False
    # 非法值回落默认
    assert AppConfig.from_dict({"weak_review_enabled": "随便"}).weak_review_enabled is True


def test_weak_review_enabled_roundtrip(config_store: ConfigStore) -> None:
    """错题提醒开关落盘可读回。"""

    config_store.save(AppConfig(weak_review_enabled=False))
    loaded = config_store.load()
    assert loaded.weak_review_enabled is False
    assert loaded.to_dict()["weak_review_enabled"] is False
