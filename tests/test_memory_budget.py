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

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SRC_ROOT = _PROJECT_ROOT / "src"


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
    """FR-31（P0）：完整装配 + 运行帧循环后，Working Set 应 < 120MB。

    在**独立子进程**中测量：pytest 全量运行时前序用例会累积 Qt 对象常驻内存，
    在宿主进程内测会混入无关残留。子进程隔离后测的是核心程序的真实常驻内存。
    皮肤包投放区经 ``isolated_skins_dir``（空目录）排除第三方素材。
    """

    mb_missing = working_set_mb()
    if mb_missing is None:
        pytest.skip("当前环境无法测量 Working Set，跳过（不做编造）")

    import os
    import subprocess
    import textwrap

    empty_skins = tmp_path / "skins-empty"
    empty_skins.mkdir()

    # 子进程脚本：装配 controller + 60 帧 + 测 Working Set，打印结果到 stdout。
    script = textwrap.dedent(
        f"""
        import sys, os, time, ctypes, ctypes.wintypes as wt
        from pathlib import Path

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        sys.path.insert(0, r"{_SRC_ROOT}")
        sys.path.insert(0, r"{_PROJECT_ROOT}")

        from desktop_pet.core import paths
        from desktop_pet.core.config import AppConfig, ConfigStore
        from desktop_pet.app.controller import PetAppController

        # 皮肤包投放区重定向到空目录（测试隔离，不加载本机 skins/）
        paths.skins_dir = lambda: Path(r"{empty_skins}")

        class _PMC(ctypes.Structure):
            _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t),
                        ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t),
                        ("PeakPagefileUsage", ctypes.c_size_t)]

        def wsmb():
            fn = ctypes.windll.psapi.GetProcessMemoryInfo
            fn.argtypes = [wt.HANDLE, ctypes.POINTER(_PMC), wt.DWORD]
            fn.restype = wt.BOOL
            c = _PMC(); c.cb = ctypes.sizeof(c)
            h = ctypes.windll.kernel32.GetCurrentProcess()
            fn(h, ctypes.byref(c), ctypes.sizeof(c))
            return c.WorkingSetSize / (1024.0 * 1024.0)

        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])

        store = ConfigStore(Path(r"{tmp_path}") / "desktop-pet" / "config.json")
        store.save(AppConfig(listen_enabled=False))

        controller = PetAppController(app, store)
        try:
            controller.start()
            for _ in range(60):
                controller._on_frame_tick(time.monotonic())
                app.processEvents()
            print(f"MEM_MB={{wsmb():.1f}}")
        finally:
            controller.shutdown()
            app.processEvents()
        """
    )

    proc = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, f"子进程失败：\n{proc.stderr}"

    import re

    match = re.search(r"MEM_MB=([\d.]+)", proc.stdout)
    assert match, f"未解析到内存读数：\n{proc.stdout}"
    mb = float(match.group(1))
    print(f"\n[memory] 独立进程完整装配+60帧后 Working Set = {mb:.1f} MB (上限 120MB)")
    assert mb < 120.0, f"内存超限：{mb:.1f}MB >= 120MB (FR-31)"


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
