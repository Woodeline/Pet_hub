"""pytest 全局夹具与运行环境准备。

关键点：
- 强制 Qt 使用 ``offscreen`` 平台，测试期间不弹出真实窗口、不影响用户桌面。
- 把 ``src`` 与项目根加入 ``sys.path``（即使未安装为包也能导入）。
- 提供**临时目录**配置夹具，确保任何配置读写都落在 ``tmp_path``，
  **绝不污染用户真实的 ``%APPDATA%\\desktop-pet\\``（FR-39 测试隔离）。**
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# 必须在任何 QApplication 创建之前设置，否则无效（Qt 在创建应用时读取该变量）。
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_ROOT = _PROJECT_ROOT / "src"

for _path in (str(_SRC_ROOT), str(_PROJECT_ROOT)):
    if _path not in sys.path:
        sys.path.insert(0, _path)


@pytest.fixture(scope="session")
def project_root() -> Path:
    """项目根目录。"""

    return _PROJECT_ROOT


@pytest.fixture(scope="session")
def src_root() -> Path:
    """源码根目录 ``src/desktop_pet``。"""

    return _SRC_ROOT / "desktop_pet"


@pytest.fixture()
def config_path(tmp_path: Path) -> Path:
    """一个位于临时目录的配置文件路径（不存在）。"""

    return tmp_path / "desktop-pet" / "config.json"


@pytest.fixture()
def config_store(config_path: Path):
    """指向临时目录的 :class:`ConfigStore`，用于配置容错测试。"""

    from desktop_pet.core.config import ConfigStore

    return ConfigStore(config_path)


@pytest.fixture()
def isolated_appdata(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """把 ``APPDATA`` 重定向到临时目录，避免任何 ``default_path()`` 调用写真实用户目录。"""

    appdata = tmp_path / "APPDATA"
    appdata.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("APPDATA", str(appdata))
    return appdata
