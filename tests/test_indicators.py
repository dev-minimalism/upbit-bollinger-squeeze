"""지표 계산과 신호 생성의 현재 동작을 고정하는 테스트.

모니터와 백테스터에 중복된 공식을 하나로 합치기 전의 안전망이다.
"""

from dataclasses import replace

import numpy as np
import pandas as pd

from strategy import StrategyParams, compute_indicators

INDICATOR_COLUMNS = [
    "SMA",
    "STD",
    "Upper_Band",
    "Lower_Band",
    "Band_Width",
    "Volatility_Squeeze",
    "BB_Position",
    "RSI",
    "Buy_Signal",
    "Sell_50_Signal",
    "Sell_All_Signal",
]


def test_short_series_is_returned_without_indicators(monitor, make_ohlcv):
    # volatility_lookback(50)보다 짧으면 지표를 붙이지 않고 그대로 돌려준다.
    out = monitor.calculate_indicators(make_ohlcv(np.full(49, 100.0)))
    assert not set(INDICATOR_COLUMNS) & set(out.columns)


def test_all_indicator_columns_are_added(monitor, breakout_df):
    out = monitor.calculate_indicators(breakout_df)
    assert set(INDICATOR_COLUMNS) <= set(out.columns)


def test_bands_bracket_sma_and_position_is_normalised(monitor, breakout_df):
    out = monitor.calculate_indicators(breakout_df).dropna(subset=["SMA"])
    assert (out["Upper_Band"] >= out["SMA"]).all()
    assert (out["SMA"] >= out["Lower_Band"]).all()
    inside = (out["close"] <= out["Upper_Band"]) & (out["close"] >= out["Lower_Band"])
    assert out.loc[inside, "BB_Position"].between(0, 1).all()


def test_rsi_saturates_on_monotonic_moves(monitor, make_ohlcv):
    up = monitor.calculate_indicators(make_ohlcv(100 + np.arange(80) * 0.5))
    down = monitor.calculate_indicators(make_ohlcv(200 - np.arange(80) * 0.5))
    # 손실 창이 전부 0이면 rs = inf -> RSI 100, 이익 창이 전부 0이면 rs = 0 -> RSI 0
    assert (up["RSI"].iloc[14:] == 100).all()
    assert (down["RSI"].iloc[14:] == 0).all()


def test_squeeze_is_relative_to_recent_history(monitor, breakout_df):
    squeeze = monitor.calculate_indicators(breakout_df)["Volatility_Squeeze"]
    # Band_Width는 20일, 그 위의 50일 분위수는 추가로 49일이 필요하다: 68행까지는 절대 켜지지 않는다.
    assert not squeeze.iloc[:68].any()
    # 변동성이 일정한 구간에서는 "하위 20%" 규칙이 대략 5일 중 1일을 플래그한다.
    steady = squeeze.iloc[68:100]
    assert 0.05 < steady.mean() < 0.5
    # 상승 구간 끝에서는 밴드폭이 창 안의 최솟값이라 매일 켜진다.
    assert squeeze.iloc[-10:].all()


def test_buy_signal_needs_overbought_rsi_inside_squeeze(monitor, breakout_df):
    out = monitor.calculate_indicators(breakout_df)
    high_vol, ramp = out.iloc[:100], out.iloc[100:]

    assert (high_vol["RSI"].dropna() < 70).all()
    assert not high_vol["Buy_Signal"].any()

    tail = ramp.iloc[14:]  # 14일 연속 상승 이후
    assert (tail["RSI"] == 100).all()
    assert tail["Volatility_Squeeze"].all()
    assert tail["Buy_Signal"].all()

    # squeeze만으로는 부족하다: 상승 초반은 squeeze지만 RSI 창에 아직 하락일이 남아 있다.
    squeezed_not_overbought = out[out["Volatility_Squeeze"] & (out["RSI"] <= 70)]
    assert len(squeezed_not_overbought) > 0
    assert not squeezed_not_overbought["Buy_Signal"].any()


def test_default_params_have_no_indicator_based_half_exit(monitor, breakout_df):
    # 기본 전략의 50% 익절은 진입가 기준(take_profit_hit)이라 지표 컬럼에는 나타나지 않는다.
    assert not monitor.calculate_indicators(breakout_df)["Sell_50_Signal"].any()


def test_legacy_band_rule_when_take_profit_is_unset(breakout_df):
    legacy = replace(StrategyParams(), take_profit_pct=None, reduce_on_midband=True)
    out = compute_indicators(breakout_df, legacy).dropna(subset=["BB_Position"])
    pos = out["BB_Position"]
    expected_50 = (pos >= 0.8) | ((pos - 0.5).abs() <= 0.1)
    pd.testing.assert_series_equal(out["Sell_50_Signal"], expected_50, check_names=False)
    assert out["Sell_50_Signal"].any() and not out["Sell_50_Signal"].all()


def test_sell_all_threshold(monitor, make_ohlcv):
    # 급락 구간: 종가가 20일 창의 최솟값이라 하단 밴드 근처(위치 <= 0.1)에 머문다.
    crash = make_ohlcv(
        np.concatenate([100 + 3 * np.sin(np.arange(60) * 0.5), 100 - np.arange(1, 21) * 2.0])
    )
    out = monitor.calculate_indicators(crash).dropna(subset=["BB_Position"])
    pd.testing.assert_series_equal(
        out["Sell_All_Signal"], out["BB_Position"] <= 0.1, check_names=False
    )
    assert out["Sell_All_Signal"].iloc[-1]
    assert not out["Sell_All_Signal"].iloc[0]


def test_monitor_and_backtest_indicators_agree(monitor, backtest, breakout_df):
    """두 모듈의 지표 공식은 현재 동일하다. 이 테스트가 깨지면 한쪽만 바뀐 것이다."""
    from_monitor = monitor.calculate_indicators(breakout_df.copy())
    from_backtest = backtest.calculate_technical_indicators(breakout_df.copy())
    pd.testing.assert_frame_equal(from_monitor, from_backtest)
