"""内存占用实测（FR-31：常驻内存 < 120MB）。

在 Windows 上用 ``ctypes`` 调 ``psapi.GetProcessMemoryInfo`` 读取当前进程
Working Set。这是**真实测量**，不是估算；若平台不支持则明确 skip（不编造数字）。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import sys
from pathlib import Path

import pytest

from desktop_pet.core.config import AppConfig, ConfigStore

_MB = 1024.0 * 1024.0


class _PROCESS_MEMORY_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("cb", wt.DWORD),
        ("PageFaultCount", wt.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t),
        ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t),
        ("PeakPagefileUsage", ctypes.c_size_t),
    ]


def working_set_mb() -> float | None:
    """返回当前进程 Working Set（MB）；不支持则返回 None。"""

    if sys.platform != "win32":
        return None
    try:
        fn = ctypes.windll.psapi.GetProcessMemoryInfo
        fn.argtypes = [wt.HANDLE, ctypes.POINTER(_PROCESS_MEMORY_COUNTERS), wt.DWORD]
        fn.restype = wt.BOOL
        counters = _PROCESS_MEMORY_COUNTERS()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ok = fn(handle, ctypes.byref(counters), counters.cb)
        if not ok:
            return None
        return counters.WorkingSetSize / _MB
    except Exception:  # noqa: BLE001
        return None


def test_working_set_measurement_is_available() -> None:
    mb = working_set_mb()
    if mb is None:
        pytest.skip("当前环境无法测量 Working Set（非 Windows 或 psapi 不可用）")
    assert mb > 0.0


def test_memory_budget_under_120mb(qtbot, tmp_path: Path) -> None:
    """FR-31（P0）：完整装配 + 运行帧循环后，Working Set 应 < 120MB。"""

    mb_missing = working_set_mb()
    if mb_missing is None:
        pytest.skip("当前环境无法测量 Working Set，跳过（不做编造）")

    from PySide6.QtWidgets import QApplication

    from desktop_pet.app.controller import PetAppController

    # 关闭键盘监听，避免测试时钩住用户的真实键盘
    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(AppConfig(listen_enabled=False))

    app = QApplication.instance()
    assert isinstance(app, QApplication)

    controller = PetAppController(app, store)
    try:
        controller.start()
        # 运行 ~2 秒的帧循环（30fps）
        import time

        for _ in range(60):
            controller._on_frame_tick(time.monotonic())
            app.processEvents()

        mb = working_set_mb()
        print(f"\n[memory] 完整装配+60帧后 Working Set = {mb:.1f} MB (上限 120MB)")
        assert mb is not None
        assert mb < 120.0, f"内存超限：{mb:.1f}MB >= 120MB (FR-31)"
    finally:
        controller.shutdown()
        app.processEvents()


def test_memory_stable_over_many_frames(qtbot, tmp_path: Path) -> None:
    """长时间帧循环不应持续增长（无内存泄漏迹象）。"""

    if working_set_mb() is None:
        pytest.skip("当前环境无法测量 Working Set")

    from PySide6.QtWidgets import QApplication

    from desktop_pet.app.controller import PetAppController

    store = ConfigStore(tmp_path / "desktop-pet" / "config.json")
    store.save(AppConfig(listen_enabled=False))
    app = QApplication.instance()
    assert isinstance(app, QApplication)

    controller = PetAppController(app, store)
    try:
        controller.start()
        import time

        for _ in range(120):
            controller._on_frame_tick(time.monotonic())
            app.processEvents()
        after_warmup = working_set_mb()

        for _ in range(600):
            controller._on_frame_tick(time.monotonic())
            app.processEvents()
        after_load = working_set_mb()

        assert after_warmup is not None and after_load is not None
        growth = after_load - after_warmup
        print(f"\n[memory] 预热后 {after_warmup:.1f}MB → 再加 600 帧 {after_load:.1f}MB "
              f"(增长 {growth:+.1f}MB)")
        # 允许少量抖动，但不应显著增长（例如 > 10MB 视为可疑）
        assert growth < 10.0, f"帧循环疑似内存泄漏，增长 {growth:.1f}MB"
    finally:
        controller.shutdown()
        app.processEvents()
