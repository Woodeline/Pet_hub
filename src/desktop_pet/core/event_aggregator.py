"""core.event_aggregator —— 敲击滚动窗口聚合并判定高频（FR-03）。

**本模块禁止 import 任何图形界面（Qt/GUI）库。**

设计要点：
- 使用 ``collections.deque`` 保存时间窗内的时间戳，记录时剔除过期项。
- 使用硬上限 ``_MAX_WINDOW_SAMPLES`` 保证**按键风暴下内存不无限增长**。
- 时间戳由调用方以秒（float）注入，不自行取时钟。
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Final, Optional

from desktop_pet.core import constants as C

#: 单个窗口内保留的最大时间戳数量（防按键风暴内存膨胀的硬上限）。
_MAX_WINDOW_SAMPLES: Final[int] = 64


@dataclass
class KeystrokeResult:
    """一次按键记录的聚合结果。

    Attributes:
        burst_count: 当前滚动窗口内的按键次数。
        high_frequency: 是否判定为高频敲击（窗口内 >= 阈值）。
        rate_per_sec: 由窗口长度折算的每秒敲击速率。
    """

    burst_count: int = 0
    high_frequency: bool = False
    rate_per_sec: float = 0.0


class KeystrokeAggregator:
    """敲击时间窗聚合器（300ms 窗口内 >=3 次判定高频，FR-03）。"""

    def __init__(
        self,
        window_ms: float = C.HIGH_FREQ_WINDOW_MS,
        threshold: int = C.HIGH_FREQ_THRESHOLD,
    ) -> None:
        """构造聚合器。

        Args:
            window_ms: 滚动窗口长度（毫秒）。
            threshold: 高频判定阈值（窗口内按键次数）。
        """

        self._window_s: float = max(1e-6, float(window_ms) / 1000.0)
        self._threshold: int = max(1, int(threshold))
        self._timestamps: Deque[float] = deque()
        self._high_freq: bool = False
        #: 上次成功记录的时间戳，用于检测时间倒退（时钟异常）。``None`` 表示尚未记录。
        self._last_ts: Optional[float] = None

    # ------------------------------------------------------------------ #
    # 公共 API
    # ------------------------------------------------------------------ #
    def record(self, timestamp: float) -> KeystrokeResult:
        """记录一次按键并返回聚合结果。

        Args:
            timestamp: 按键时刻（秒，建议来自 ``time.monotonic()``）。

        Returns:
            当前窗口的 :class:`KeystrokeResult`。

        Note:
            **防御性处理（时间倒退 / 时钟异常）**：若 ``timestamp`` 早于上次记录
            时刻，则视为时间轴非单调。此时不写入该时间戳，而是**清空窗口并从新
            时间点重启**，避免陈旧样本因无法被 ``cutoff`` 剔除而导致计数值虚高。
            正常单调路径的行为完全不变。
        """

        ts = float(timestamp)
        # 时钟异常（时间倒退）：清空窗口并重启，不把倒退的时间戳写入 deque。
        if self._last_ts is not None and ts < self._last_ts:
            self.reset()
            self._last_ts = ts
            return KeystrokeResult(burst_count=0, high_frequency=False, rate_per_sec=0.0)

        self._last_ts = ts
        self._timestamps.append(ts)
        self._prune(ts)
        count = len(self._timestamps)
        self._high_freq = count >= self._threshold
        rate = count / self._window_s if self._window_s > 0.0 else 0.0
        return KeystrokeResult(
            burst_count=count,
            high_frequency=self._high_freq,
            rate_per_sec=rate,
        )

    def is_high_frequency(self) -> bool:
        """返回最近一次 :meth:`record` 得到的高频判定。"""

        return self._high_freq

    def burst_count(self, now: float | None = None) -> int:
        """返回当前窗口内的按键次数（可选传入 ``now`` 触发一次过期清理）。"""

        if now is not None:
            self._prune(float(now))
        return len(self._timestamps)

    def reset(self) -> None:
        """清空窗口与高频标志（同时复位记录时间戳基准）。"""

        self._timestamps.clear()
        self._high_freq = False
        self._last_ts = None

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _prune(self, now: float) -> None:
        """剔除窗口外时间戳，并强制硬上限防止内存无限增长。"""

        cutoff = now - self._window_s
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        while len(self._timestamps) > _MAX_WINDOW_SAMPLES:
            self._timestamps.popleft()


__all__ = ["KeystrokeResult", "KeystrokeAggregator"]
