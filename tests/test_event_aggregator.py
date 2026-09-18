"""敲击聚合器测试（FR-03：300ms 窗口内 >=3 次判定高频）。"""

from __future__ import annotations

import pytest

from desktop_pet.core import constants as C
from desktop_pet.core.event_aggregator import KeystrokeAggregator


def make_agg(window_ms: float = C.HIGH_FREQ_WINDOW_MS, threshold: int = C.HIGH_FREQ_THRESHOLD):
    return KeystrokeAggregator(window_ms=window_ms, threshold=threshold)


# --------------------------------------------------------------------------- #
# 1. 判定边界：窗口内 2 / 3 / 4 次
# --------------------------------------------------------------------------- #
def test_two_keystrokes_not_high_frequency() -> None:
    agg = make_agg()
    agg.record(0.0)
    result = agg.record(0.1)
    assert result.burst_count == 2
    assert result.high_frequency is False


def test_three_keystrokes_is_high_frequency() -> None:
    agg = make_agg()
    agg.record(0.0)
    agg.record(0.1)
    result = agg.record(0.2)
    assert result.burst_count == 3
    assert result.high_frequency is True
    assert agg.is_high_frequency() is True


def test_four_keystrokes_is_high_frequency() -> None:
    agg = make_agg()
    for t in (0.0, 0.05, 0.1, 0.15):
        result = agg.record(t)
    assert result.burst_count == 4
    assert result.high_frequency is True


def test_default_thresholds_match_prd() -> None:
    agg = make_agg()
    assert agg._threshold == C.HIGH_FREQ_THRESHOLD == 3


# --------------------------------------------------------------------------- #
# 2. 窗口滑动正确性
# --------------------------------------------------------------------------- #
def test_event_just_outside_window_is_dropped() -> None:
    agg = make_agg()
    agg.record(0.0)
    result = agg.record(0.301)  # 超出 300ms
    assert result.burst_count == 1
    assert result.high_frequency is False


def test_event_at_exact_window_edge_is_kept() -> None:
    """窗口边界按 [now-0.3, now] 闭区间处理：t=0 与 t=0.3 视为同窗。"""

    agg = make_agg()
    agg.record(0.0)
    result = agg.record(0.3)
    assert result.burst_count == 2


def test_sliding_window_evicts_stale_events() -> None:
    agg = make_agg()
    for t in (0.0, 0.1, 0.2):
        agg.record(t)
    assert agg.is_high_frequency() is True

    # 跳到 0.51：0/0.1/0.2 全部过期，只剩本次
    result = agg.record(0.51)
    assert result.burst_count == 1
    assert result.high_frequency is False


def test_rate_per_sec_computed_from_window() -> None:
    agg = make_agg()
    agg.record(0.0)
    agg.record(0.1)
    result = agg.record(0.2)
    # 3 次 / 0.3s 窗口
    assert result.rate_per_sec == pytest.approx(10.0)


# --------------------------------------------------------------------------- #
# 3. 按键风暴：内存硬上限（防无限增长）
# --------------------------------------------------------------------------- #
def test_storm_same_timestamp_bounded() -> None:
    agg = make_agg()
    for _ in range(100_000):
        agg.record(1.0)
    # 内部 deque 必须被硬上限约束，不能无限增长
    assert len(agg._timestamps) <= 64
    assert agg.burst_count() <= 64


def test_storm_increasing_timestamps_bounded() -> None:
    agg = make_agg()
    for i in range(100_000):
        agg.record(i * 0.001)  # 每次 +1ms，远密于窗口
    assert len(agg._timestamps) <= 64
    assert agg.burst_count(i * 0.001) <= 64


def test_storm_randomised_bounded() -> None:
    import random

    rng = random.Random(1234)
    agg = make_agg()
    t = 0.0
    for _ in range(100_000):
        t += rng.uniform(0.0, 0.002)
        agg.record(t)
    assert len(agg._timestamps) <= 64


# --------------------------------------------------------------------------- #
# 4. 复位 / 自定义窗口
# --------------------------------------------------------------------------- #
def test_reset_clears_state() -> None:
    agg = make_agg()
    for t in (0.0, 0.1, 0.2):
        agg.record(t)
    agg.reset()
    assert agg.burst_count() == 0
    assert agg.is_high_frequency() is False


def test_custom_window_and_threshold() -> None:
    agg = make_agg(window_ms=500.0, threshold=4)
    for t in (0.0, 0.1, 0.2):
        result = agg.record(t)
    assert result.high_frequency is False  # 只有 3 次，阈值是 4
    result = agg.record(0.4)
    assert result.burst_count == 4
    assert result.high_frequency is True


def test_burst_count_with_now_prunes() -> None:
    agg = make_agg()
    for t in (0.0, 0.1, 0.2):
        agg.record(t)
    assert agg.burst_count(1.0) == 0  # 传入新 now，全部过期


# --------------------------------------------------------------------------- #
# 5. 异常输入（时间倒退）——视为时钟异常，清空窗口并重启，不崩溃
# --------------------------------------------------------------------------- #
def test_time_reversal_does_not_crash() -> None:
    """非单调时间戳（时钟异常）：清空窗口并重启，绝不崩溃。

    防御性策略（FR-03 收口）：检测到时间倒退时清空窗口、丢弃该次记录，
    避免因时间轴非单调导致陈旧样本无法被 cutoff 剔除、计数虚高。
    真实场景下时间戳来自 ``time.monotonic()``（保证单调），故此为健壮性边角，
    严重级别 P2。
    """

    agg = make_agg()
    agg.record(1000.0)
    agg.record(1000.1)
    agg.record(1000.2)
    result = agg.record(0.0)  # 时间倒退 → 视为时钟异常，清空窗口并重启
    assert result.burst_count == 0
    assert result.high_frequency is False
    assert isinstance(result.rate_per_sec, float)

    # 清空后从新时间点重启：后续单调敲击正常累积
    assert agg.record(0.1).burst_count == 1
    assert agg.record(0.2).burst_count == 2


def test_extreme_window_values_do_not_crash() -> None:
    agg = KeystrokeAggregator(window_ms=0.0, threshold=1)
    result = agg.record(0.0)
    assert result.burst_count == 1
    assert result.rate_per_sec >= 0.0


# --------------------------------------------------------------------------- #
# 6. 时钟防御语义（本轮新增逻辑）——单调路径不变 / 倒退清空 / 相同时间戳不误判
# --------------------------------------------------------------------------- #
def test_same_timestamp_is_not_treated_as_reversal() -> None:
    """相等时间戳（同一毫秒内高频敲击）必须正常累计，不能被误判为时钟异常。"""

    agg = make_agg()
    assert agg.record(5.0).burst_count == 1
    assert agg.record(5.0).burst_count == 2
    result = agg.record(5.0)
    assert result.burst_count == 3
    assert result.high_frequency is True


def test_non_decreasing_sequence_counts_normally() -> None:
    """非递减（含相等）序列的计数序列与修复前一致。"""

    agg = make_agg()
    seq = [0.0, 0.0, 0.1, 0.1, 0.2]
    counts = [agg.record(t).burst_count for t in seq]
    assert counts == [1, 2, 3, 4, 5]


def test_micro_reversal_behaves_like_large_reversal() -> None:
    """微小倒退（浮点误差 1e-9）与大幅倒退（-1000s）表现一致：清空、计数 0。"""

    for reversed_ts in (1000.2 - 1e-9, 1000.2 - 1000.0):
        agg = make_agg()
        agg.record(1000.0)
        agg.record(1000.1)
        agg.record(1000.2)
        result = agg.record(reversed_ts)
        assert result.burst_count == 0, f"倒退到 {reversed_ts} 未清空"
        assert result.high_frequency is False
        assert agg.burst_count() == 0


def test_reversed_timestamp_not_retained_in_window() -> None:
    agg = make_agg()
    agg.record(500.0)
    agg.record(500.1)
    agg.record(0.0)  # 倒退
    assert list(agg._timestamps) == [], "倒退的时间戳不应被写入窗口"


def test_recovery_after_reversal_restores_high_frequency() -> None:
    agg = make_agg()
    agg.record(1000.0)
    agg.record(1000.1)
    agg.record(0.0)  # 倒退 → 清空
    # 从新时间点重启，300ms/3 次判定应恢复
    assert agg.record(0.1).burst_count == 1
    assert agg.record(0.2).burst_count == 2
    result = agg.record(0.25)
    assert result.burst_count == 3
    assert result.high_frequency is True


def test_reset_clears_last_ts_baseline() -> None:
    """reset() 后基准时间戳复位：任意新时间戳（哪怕更小）都能正常起始。"""

    agg = make_agg()
    agg.record(1000.0)
    agg.reset()
    assert agg.record(0.0).burst_count == 1

