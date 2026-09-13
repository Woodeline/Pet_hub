"""配置容错测试（FR-36/37/38/39，架构 §9.6）。

**隔离要求**：所有读写都使用 ``tmp_path``，绝不触碰真实 ``%APPDATA%``。
"""

from __future__ import annotations

import json
import os
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
        "jp_enabled", "jp_level",
        "jp_bubble_duration_s", "jp_daily_limit",
    }


# --------------------------------------------------------------------------- #
# 3.5 日语学习可调参数（JP-17/18）
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,expected",
    [
        (30, 30.0),            # 合法
        ("60", 60.0),          # 数字字符串
        (3, 5.0),              # 低于下限 → 钳到 5
        (999, 120.0),          # 高于上限 → 钳到 120
        ("abc", 30.0),         # 非法 → 默认 30
        (True, 30.0),          # bool 非法
        (None, 30.0),
    ],
)
def test_jp_bubble_duration_coercion(raw, expected) -> None:
    cfg = AppConfig.from_dict({"jp_bubble_duration_s": raw})
    assert cfg.jp_bubble_duration_s == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        (15, 15),              # 合法
        ("20", 20),            # 数字字符串
        (0, 1),                # 低于下限 → 钳到 1
        (9999, 500),           # 高于上限 → 钳到 500
        ("abc", 15),           # 非法 → 默认 15
        (True, 15),            # bool 非法
        (3.5, 15),             # 非整数浮点非法
        (None, 15),
    ],
)
def test_jp_daily_limit_coercion(raw, expected) -> None:
    cfg = AppConfig.from_dict({"jp_daily_limit": raw})
    assert cfg.jp_daily_limit == expected


def test_jp_new_fields_default_values() -> None:
    cfg = AppConfig()
    assert cfg.jp_bubble_duration_s == C.JP_BUBBLE_DURATION_DEFAULT_S == 30.0
    assert cfg.jp_daily_limit == C.JP_DAILY_LIMIT_DEFAULT == 15


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

    store = ConfigStore(tmp_path / "config.json")
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
