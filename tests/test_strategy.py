"""strategy.py: 파라미터 프리셋과 compute_indicators의 파라미터 연결을 검증한다."""

import numpy as np
import pandas as pd
import pytest

from strategy import INDICATOR_COLUMNS, STRATEGY_PRESETS, StrategyParams, compute_indicators
from upbit_realtime_monitor import UpbitRealTimeVolatilityMonitor


def test_default_params_equal_conservative_preset():
    assert StrategyParams() == STRATEGY_PRESETS["conservative"]
    assert StrategyParams.from_mode("conservative") is STRATEGY_PRESETS["conservative"]


def test_unknown_mode_is_an_error():
    with pytest.raises(ValueError, match="bogus"):
        StrategyParams.from_mode("bogus")


def test_params_are_immutable():
    with pytest.raises(AttributeError):
        StrategyParams().rsi_overbought = 10


def test_min_rows_is_the_longest_window():
    assert StrategyParams().min_rows == 50
    assert StrategyParams(bb_period=80).min_rows == 80


def test_compute_indicators_does_not_mutate_input(breakout_df):
    before = breakout_df.copy()
    out = compute_indicators(breakout_df, StrategyParams())
    pd.testing.assert_frame_equal(breakout_df, before)
    assert out is not breakout_df
    assert set(INDICATOR_COLUMNS) <= set(out.columns)


def test_short_input_is_returned_as_is(make_ohlcv):
    df = make_ohlcv(np.full(49, 100.0))
    assert compute_indicators(df, StrategyParams()) is df


@pytest.mark.parametrize("mode", list(STRATEGY_PRESETS))
def test_signals_follow_the_given_thresholds(mode, breakout_df):
    """신호 컬럼이 전달받은 파라미터의 임계값을 그대로 쓰는지, 프리셋별로 확인한다."""
    p = STRATEGY_PRESETS[mode]
    out = compute_indicators(breakout_df, p).dropna(subset=["RSI", "BB_Position"])
    pos, rsi = out["BB_Position"], out["RSI"]

    expected_buy = (rsi > p.rsi_overbought) & out["Volatility_Squeeze"]
    expected_50 = (pos >= p.bb_sell_threshold) | ((pos - 0.5).abs() <= 0.1)
    expected_all = pos <= p.bb_sell_all_threshold
    pd.testing.assert_series_equal(out["Buy_Signal"], expected_buy, check_names=False)
    pd.testing.assert_series_equal(out["Sell_50_Signal"], expected_50, check_names=False)
    pd.testing.assert_series_equal(out["Sell_All_Signal"], expected_all, check_names=False)


def test_looser_preset_sells_more_often(breakout_df):
    # aggressive(0.7 / 0.2)는 conservative(0.8 / 0.1)의 매도 신호를 포함하는 상위집합이다.
    cons = compute_indicators(breakout_df, STRATEGY_PRESETS["conservative"])
    aggr = compute_indicators(breakout_df, STRATEGY_PRESETS["aggressive"])
    assert (aggr["Sell_50_Signal"] | ~cons["Sell_50_Signal"]).all()
    assert (aggr["Sell_All_Signal"] | ~cons["Sell_All_Signal"]).all()
    assert aggr["Sell_All_Signal"].sum() >= cons["Sell_All_Signal"].sum()


def test_monitor_uses_injected_params(breakout_df):
    monitor = UpbitRealTimeVolatilityMonitor(params=STRATEGY_PRESETS["aggressive"])
    assert monitor.params is STRATEGY_PRESETS["aggressive"]
    out = monitor.calculate_indicators(breakout_df)
    expected = compute_indicators(breakout_df, STRATEGY_PRESETS["aggressive"])
    pd.testing.assert_frame_equal(out, expected)
