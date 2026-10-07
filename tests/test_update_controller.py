"""工程师自测：检查更新的 controller 侧 —— 手动/自动差异化反馈与 7 天节流。

不真的联网：成功/失败回调直接注入 ReleaseInfo / 消息；自动检查用
``_start_update_check`` 替身捕获触发（无网络、无线程）。

覆盖：
1. 手动成功：有新版 → 通知新版；同版 → 通知已最新；均记录检查时刻并复位在途标志。
2. 自动成功：仅新版通知，同版静默。
3. 失败：手动通知失败原因，自动静默；两条路径都记录检查时刻（防离线反复重试）。
4. 自动节流：开关关 / 距上次 < 7 天 → 不查询；首次（无记录）→ 查询。
5. 在途防连点：``_update_checking`` 为真时手动检查被忽略。
"""

from __future__ import annotations

import random
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from desktop_pet.app.controller import PetAppController, _iso_shift
from desktop_pet.core.config import ConfigStore
from desktop_pet.core.daily_log_store import DailyLogStore
from desktop_pet.core.mastered_store import MasteredStore
from desktop_pet.core.update_client import ReleaseInfo
from desktop_pet.core.vocab_store import VocabStore
from desktop_pet.core.vocabulary import WordBank
from desktop_pet.core.weighted_picker import WeightedWordPicker

_NEW_RELEASE = ReleaseInfo(
    tag_name="v9.9.9", name="x", html_url="https://example.com/release"
)


@pytest.fixture()
def ctrl(qapp: QApplication, tmp_path: Path) -> PetAppController:
    """构造最小 controller（同 test_review_scheduler 范式）。"""

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    controller = PetAppController(qapp, store)

    controller._cfg.jp_enabled = False
    controller._bank = WordBank.empty()
    controller._rng = random.Random(0)
    controller._picker = WeightedWordPicker(controller._bank, controller._rng)
    controller._mastered = MasteredStore(tmp_path / "mastered.json")
    controller._daily_log = DailyLogStore(tmp_path / "daily_log.json")
    controller._vocab = VocabStore(tmp_path / "vocab.json")
    controller._mastered.load()
    controller._daily_log.load()
    controller._vocab.load()
    controller._now_iso = lambda: "2025-01-01T00:00:00Z"
    return controller


class _NotifySpy:
    """托盘通知替身：记录 (title, message) 并可禁用真实弹窗。"""

    def __init__(self, controller: PetAppController) -> None:
        self.calls: list[str] = []
        self._original = controller._tray.notify

        def spy(title: str, message: str) -> None:
            self.calls.append(message)

        controller._tray.notify = spy  # type: ignore[method-assign]

    def joined(self) -> str:
        return "\n".join(self.calls)


def test_manual_success_new_version_notifies(ctrl: PetAppController) -> None:
    spy = _NotifySpy(ctrl)
    ctrl._on_update_check_succeeded(_NEW_RELEASE, manual=True)

    assert "v9.9.9" in spy.joined()
    assert ctrl._cfg.update_check_last_at == "2025-01-01T00:00:00Z"
    assert ctrl._update_checking is False


def test_manual_success_same_version_notifies_latest(ctrl: PetAppController) -> None:
    spy = _NotifySpy(ctrl)
    ctrl._on_update_check_succeeded(
        ReleaseInfo(tag_name="v0.6.2", name="x", html_url=""), manual=True
    )
    assert "已是最新版本" in spy.joined()


def test_auto_success_same_version_silent(ctrl: PetAppController) -> None:
    spy = _NotifySpy(ctrl)
    ctrl._on_update_check_succeeded(
        ReleaseInfo(tag_name="v0.6.2", name="x", html_url=""), manual=False
    )
    assert spy.calls == []
    assert ctrl._cfg.update_check_last_at != ""


def test_failed_manual_notifies_but_auto_silent(ctrl: PetAppController) -> None:
    spy = _NotifySpy(ctrl)
    ctrl._on_update_check_failed("网络不可达：boom", manual=True)
    assert "网络不可达" in spy.joined()

    ctrl._cfg.update_check_last_at = ""
    ctrl._on_update_check_failed("down", manual=False)
    assert ctrl._cfg.update_check_last_at != ""
    assert spy.calls.count("down") == 0


def test_auto_check_requires_enabled(ctrl: PetAppController) -> None:
    """开关关：不查询。"""

    ctrl._cfg.update_check_enabled = False
    started: list[bool] = []
    ctrl._start_update_check = lambda **kwargs: started.append(True)  # type: ignore[method-assign]
    ctrl._maybe_auto_update_check()
    assert started == []
    assert ctrl._update_checking is False


def test_auto_check_throttled_within_interval(ctrl: PetAppController) -> None:
    """距上次检查不足 7 天：不查询（墙钟替身钉死时刻）。"""

    ctrl._cfg.update_check_enabled = True
    ctrl._cfg.update_check_last_at = _iso_shift("2025-01-01T00:00:00Z", days=-1)
    wall = _iso_shift("2025-01-01T00:00:00Z", days=-1)
    import datetime as _dt

    epoch = _dt.datetime.strptime(wall, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=_dt.timezone.utc
    ).timestamp()
    ctrl._wall_now = lambda: epoch
    started: list[bool] = []
    ctrl._start_update_check = lambda **kwargs: started.append(True)  # type: ignore[method-assign]

    ctrl._maybe_auto_update_check()
    assert started == []


def test_auto_check_first_run_starts(ctrl: PetAppController) -> None:
    """开启后首次（无检查记录）：启动一次自动检查（manual=False）。"""

    ctrl._cfg.update_check_enabled = True
    ctrl._cfg.update_check_last_at = ""
    started: list[dict] = []
    ctrl._start_update_check = lambda *, manual: started.append({"manual": manual})  # type: ignore[method-assign]

    ctrl._maybe_auto_update_check()
    assert started == [{"manual": False}]
    assert ctrl._update_checking is True


def test_manual_check_ignored_when_in_flight(ctrl: PetAppController) -> None:
    """在途标志为真：连点被忽略（不重复通知「正在检查」）。"""

    spy = _NotifySpy(ctrl)
    ctrl._update_checking = True
    started: list[bool] = []
    ctrl._start_update_check = lambda **kwargs: started.append(True)  # type: ignore[method-assign]

    ctrl._on_update_check()
    assert started == []
    assert spy.calls == []
