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


@pytest.fixture(autouse=True)
def isolated_skins_dir(
    tmp_path_factory, monkeypatch: pytest.MonkeyPatch
) -> Path:
    """把 ``skins_dir()`` 重定向到空的临时目录，隔离用户自装皮肤包。

    本机 ``skins/`` 可能装有第三方皮肤素材（如 DyberPet 原神 MOD），一旦
    :class:`PetAppController` 装配时经 ``build_skin_renderer`` 加载，会把
    数十帧 ``QPixmap`` 常驻内存，推高 FR-31 内存基线并污染「零素材」类断言。
    测试一律在空投放区下运行；皮肤包专项测试（test_skin_pack / test_skin_renderer）
    用 ``tmp_path`` 自行构造包，不依赖本 fixture。
    """

    from desktop_pet.core import paths

    empty = tmp_path_factory.mktemp("skins-empty")
    monkeypatch.setattr(paths, "skins_dir", lambda: empty)
    return empty


@pytest.fixture(autouse=True)
def no_leaked_pet_window_timers(monkeypatch: pytest.MonkeyPatch, qapp) -> None:
    """**确定性不变量守卫**：任何用例结束时不得留下活跃的 ``PetWindow`` 定时器。

    背景（QA 阻断项）：窗口级 ``QTimer``（帧循环 ``_timer`` / 空闲游走 ``_wander_timer``）
    若在用例结束时仍活跃，会在 pytest-qt teardown 的 ``processEvents()`` 窗口内触发，
    回调进入正在析构的 C++ 对象 → ``Fatal Python error: Aborted``（原生崩溃，
    Python 层 ``try/except`` 无法拦截）。该崩溃是**时序竞态**：空载时 teardown 窗口极短
    （复现率 ≈1.6%），高负载 / 慢机 / CI 下被拉长（实测 75%），概率性复现极难定位。

    因此把「概率性崩溃」换成「**确定性 FAIL**」：每个用例结束时检查本用例创建的所有
    ``PetWindow``，只要还有活跃定时器就立刻报错并指名用例 —— 让「忘收尾」在第一时间
    被抓住，而不是偶发 abort。

    顺序：先**断言**（给出可定位的失败信息），再**强制收尾**（stop + close +
    processEvents），避免已检出的泄漏继续污染后续用例。
    """

    from desktop_pet.ui.pet_window import PetWindow

    created: list = []
    orig_init = PetWindow.__init__

    def _tracked_init(self, *args, **kwargs):  # noqa: ANN002, ANN003
        orig_init(self, *args, **kwargs)
        created.append(self)

    monkeypatch.setattr(PetWindow, "__init__", _tracked_init)
    yield

    leaked: list[str] = []
    for index, window in enumerate(created):
        try:
            if window.has_active_timers():
                leaked.append(f"PetWindow#{index}（{window.objectName() or '未命名'}）")
        except RuntimeError:
            continue  # C++ 对象已析构 → 不可能再触发
    # 先强制收尾，防止已检出的泄漏在后续 teardown 中触发原生 abort
    for window in created:
        try:
            window.stop_animation()
            window.close()
        except RuntimeError:
            pass
    qapp.processEvents()
    if leaked:
        pytest.fail(
            "用例结束时仍有 PetWindow 带活跃定时器（帧循环 / 空闲游走），"
            f"会在 teardown 的 processEvents() 窗口内触发原生 abort：{leaked}。"
            "请在该用例内显式 stop_animation() / close() 收尾。"
        )
