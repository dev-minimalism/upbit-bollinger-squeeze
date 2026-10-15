"""공용 픽스처. 모든 테스트는 오프라인으로 동작한다 (pyupbit, Telegram 호출 없음)."""

import numpy as np
import pandas as pd
import pytest

from positions import PositionBook
from upbit_backtest_strategy import UpbitVolatilityBollingerBacktest
from upbit_realtime_monitor import UpbitRealTimeVolatilityMonitor


def _ohlcv_from_close(close, start="2024-01-01") -> pd.DataFrame:
    close = np.asarray(close, dtype=float)
    index = pd.date_range(start, periods=len(close), freq="D")
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": 1000.0,
        },
        index=index,
    )


@pytest.fixture
def make_ohlcv():
    """종가 배열을 pyupbit 형식의 일봉 DataFrame으로 바꾸는 팩토리."""
    return _ohlcv_from_close


@pytest.fixture
def breakout_df() -> pd.DataFrame:
    """고변동 진동 100일 뒤 완만한 단조 상승 30일.

    상승 구간은 그것을 포함하는 어떤 50일 창에서도 가장 변동성이 낮은 구간이라
    squeeze 플래그가 켜지고, 14일 연속 상승으로 RSI가 100에 도달한다.
    즉 매수 조건 두 가지가 모두 성립하는 유일한 구간이다.
    """
    hv_days, ramp_days = 100, 30
    i = np.arange(hv_days)
    high_vol = 100 + 8.0 * np.sin(i * 0.7) + 0.5 * np.cos(i * 2.3)
    ramp = high_vol[-1] + 0.05 * np.arange(1, ramp_days + 1)
    return _ohlcv_from_close(np.concatenate([high_vol, ramp]))


@pytest.fixture
def monitor() -> UpbitRealTimeVolatilityMonitor:
    # 토큰 없이 생성하면 Telegram Application이 만들어지지 않는다. 포지션 장부는 메모리에만 둔다.
    return UpbitRealTimeVolatilityMonitor(positions=PositionBook(None))


@pytest.fixture
def make_backtest(monkeypatch):
    """출력 디렉토리 생성을 막은 백테스터 팩토리. 레포에 파일을 남기지 않는다."""
    monkeypatch.setattr(
        UpbitVolatilityBollingerBacktest, "_setup_output_directories", lambda self: None
    )

    def _make(strategy_mode="conservative", initial_capital=1_000_000):
        return UpbitVolatilityBollingerBacktest(
            initial_capital=initial_capital, strategy_mode=strategy_mode
        )

    return _make


@pytest.fixture
def backtest(make_backtest) -> UpbitVolatilityBollingerBacktest:
    return make_backtest("conservative")
