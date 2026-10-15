"""백테스트 포지션 상태 머신과 성과 지표의 현재 동작을 고정하는 테스트."""

import numpy as np
import pandas as pd
import pytest


def signals_frame(close, buy=(), sell_50=(), sell_all=()) -> pd.DataFrame:
    """지표 계산을 건너뛰고 신호 컬럼을 직접 지정한 DataFrame."""
    index = pd.date_range("2024-01-01", periods=len(close), freq="D")
    df = pd.DataFrame({"close": np.asarray(close, dtype=float)}, index=index)
    for column, rows in (
        ("Buy_Signal", buy),
        ("Sell_50_Signal", sell_50),
        ("Sell_All_Signal", sell_all),
    ):
        df[column] = False
        df.loc[df.index[list(rows)], column] = True
    return df


def actions(result):
    return [t["action"] for t in result["trades"]]


def test_full_cycle_buy_half_exit_full_exit(backtest):
    df = signals_frame([100, 100, 200, 200, 50, 50], buy=[1], sell_50=[2], sell_all=[4])
    result = backtest._execute_backtest(df, "KRW-TEST")

    assert actions(result) == ["BUY", "SELL_50%", "SELL_ALL"]
    # 100만원으로 100원에 10,000개 매수. 절반을 200원에 팔아 100만원 현금,
    # 나머지 5,000개를 50원에 팔아 25만원. 최종 125만원.
    assert result["final_cash"] == pytest.approx(1_250_000)
    assert result["total_return"] == pytest.approx(25.0)
    # 매수 한 번이 두 청산과 각각 짝지어져 완료 거래 두 건(+100%, -50%)이 된다.
    assert [round(t["profit_pct"]) for t in result["completed_trades"]] == [100, -50]
    assert (result["total_trades"], result["winning_trades"]) == (2, 1)
    assert result["win_rate"] == pytest.approx(50.0)
    assert result["profit_factor"] == pytest.approx(2.0)


def test_buy_only_when_flat_and_half_exit_only_when_full(backtest):
    # 보유 중 추가 BUY 신호와 이미 절반 청산한 뒤의 SELL_50 신호는 무시된다.
    df = signals_frame([100] * 8, buy=[1, 3, 5], sell_50=[2, 4])
    assert actions(backtest._execute_backtest(df, "KRW-TEST")) == ["BUY", "SELL_50%"]


def test_reentry_allowed_after_full_exit(backtest):
    df = signals_frame([100] * 6, buy=[0, 4], sell_50=[1], sell_all=[2])
    result = backtest._execute_backtest(df, "KRW-TEST")
    assert actions(result) == ["BUY", "SELL_50%", "SELL_ALL", "BUY"]
    # 마지막 BUY는 청산 없이 끝나므로 완료 거래에 포함되지 않는다.
    assert result["total_trades"] == 2


def test_signal_precedence_on_the_same_bar(backtest):
    # 같은 봉에 여러 신호가 겹치면 BUY > SELL_50 > SELL_ALL 순으로 하나만 처리된다.
    df = signals_frame([100] * 4, buy=[0], sell_50=[1, 2], sell_all=[1, 2])
    assert actions(backtest._execute_backtest(df, "KRW-TEST")) == ["BUY", "SELL_50%", "SELL_ALL"]


def test_open_position_is_liquidated_at_last_close(backtest):
    df = signals_frame([100, 100, 150], buy=[0])
    result = backtest._execute_backtest(df, "KRW-TEST")
    assert actions(result) == ["BUY"]
    assert result["final_cash"] == pytest.approx(1_500_000)
    # 강제 청산은 거래로 기록되지 않는다.
    assert result["total_trades"] == 0


def test_max_drawdown_is_peak_to_trough_percent(backtest):
    curve = [{"portfolio_value": v} for v in [100, 120, 90, 110, 60, 80]]
    assert backtest._calculate_max_drawdown(curve) == pytest.approx(50.0)  # 120 -> 60
    assert backtest._calculate_max_drawdown([]) == 0


@pytest.mark.parametrize(
    "mode, rsi_overbought, sell_threshold, sell_all_threshold",
    [
        ("conservative", 70, 0.8, 0.1),
        ("balanced", 65, 0.75, 0.15),
        ("aggressive", 60, 0.7, 0.2),
    ],
)
def test_strategy_mode_thresholds(
    make_backtest, mode, rsi_overbought, sell_threshold, sell_all_threshold
):
    p = make_backtest(mode).params
    assert (p.rsi_overbought, p.bb_sell_threshold, p.bb_sell_all_threshold) == (
        rsi_overbought,
        sell_threshold,
        sell_all_threshold,
    )
    # 공통 파라미터는 모드와 무관하다.
    assert (p.bb_period, p.bb_std_multiplier, p.rsi_period) == (20, 2.0, 14)
    assert (p.volatility_lookback, p.volatility_threshold) == (50, 0.2)
