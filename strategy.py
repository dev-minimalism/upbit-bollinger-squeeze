# strategy.py
"""
변동성 폭파 볼린저 밴드 전략의 단일 정의.

실시간 모니터와 백테스터가 같은 파라미터 묶음(StrategyParams)과
같은 지표 함수(compute_indicators)를 사용한다. 전략 공식을 바꿀 때는 이 파일만 고친다.
"""

from dataclasses import dataclass

import pandas as pd

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


@dataclass(frozen=True)
class StrategyParams:
    """전략 파라미터. 기본값은 conservative 모드와 같다."""

    # 볼린저 밴드
    bb_period: int = 20
    bb_std_multiplier: float = 2.0
    # RSI
    rsi_period: int = 14
    rsi_overbought: float = 70
    # 변동성 압축: 밴드폭이 최근 volatility_lookback일 중 하위 volatility_threshold 분위 아래
    volatility_lookback: int = 50
    volatility_threshold: float = 0.2
    # 매도: 밴드 위치가 bb_sell_threshold 이상이면 50% 익절, bb_sell_all_threshold 이하면 전량 매도
    bb_sell_threshold: float = 0.8
    bb_sell_all_threshold: float = 0.1
    # 사람이 읽는 모드 설명 (로그, 리포트용)
    label: str = "🛡️ 보수적 전략: 안전 우선, 신중한 매매"

    @property
    def min_rows(self) -> int:
        """지표를 계산하려면 최소 몇 개의 캔들이 필요한가."""
        return max(self.bb_period, self.rsi_period, self.volatility_lookback)

    @classmethod
    def from_mode(cls, mode: str) -> "StrategyParams":
        try:
            return STRATEGY_PRESETS[mode]
        except KeyError:
            raise ValueError(
                f"알 수 없는 전략 모드: {mode!r} (가능한 값: {', '.join(STRATEGY_PRESETS)})"
            ) from None


STRATEGY_PRESETS: dict[str, StrategyParams] = {
    "conservative": StrategyParams(),
    "balanced": StrategyParams(
        rsi_overbought=65,
        bb_sell_threshold=0.75,
        bb_sell_all_threshold=0.15,
        label="⚖️ 균형 전략: 적당한 위험과 수익",
    ),
    "aggressive": StrategyParams(
        rsi_overbought=60,
        bb_sell_threshold=0.7,
        bb_sell_all_threshold=0.2,
        label="🔥 공격적 전략: 더 많은 매매 기회, 높은 수익 추구",
    ),
}


def compute_indicators(data: pd.DataFrame, params: StrategyParams) -> pd.DataFrame:
    """일봉 OHLCV에 지표와 매매 신호 컬럼을 붙인 새 DataFrame을 돌려준다.

    입력은 바꾸지 않는다. 캔들이 params.min_rows보다 적으면 지표 없이 입력 그대로 돌려준다.
    'close' 컬럼이 있어야 한다 (pyupbit.get_ohlcv 형식).
    """
    if len(data) < params.min_rows:
        return data

    data = data.copy()
    close = data["close"]

    # 볼린저 밴드
    data["SMA"] = close.rolling(window=params.bb_period).mean()
    data["STD"] = close.rolling(window=params.bb_period).std()
    data["Upper_Band"] = data["SMA"] + (data["STD"] * params.bb_std_multiplier)
    data["Lower_Band"] = data["SMA"] - (data["STD"] * params.bb_std_multiplier)

    # 밴드폭 (변동성 지표)과 변동성 압축 신호
    data["Band_Width"] = (data["Upper_Band"] - data["Lower_Band"]) / data["SMA"]
    data["Volatility_Squeeze"] = data["Band_Width"] < data["Band_Width"].rolling(
        params.volatility_lookback
    ).quantile(params.volatility_threshold)

    # 볼린저 밴드 위치 (0~1)
    data["BB_Position"] = (close - data["Lower_Band"]) / (data["Upper_Band"] - data["Lower_Band"])

    # RSI (단순 이동평균 방식)
    delta = close.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=params.rsi_period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=params.rsi_period).mean()
    rs = gain / loss
    data["RSI"] = 100 - (100 / (1 + rs))

    # 매매 신호. 매수는 의도적으로 "과매수 RSI + 변동성 압축" 조합이다 (모멘텀 돌파).
    data["Buy_Signal"] = (data["RSI"] > params.rsi_overbought) & data["Volatility_Squeeze"]
    data["Sell_50_Signal"] = (data["BB_Position"] >= params.bb_sell_threshold) | (
        abs(data["BB_Position"] - 0.5) <= 0.1
    )
    data["Sell_All_Signal"] = data["BB_Position"] <= params.bb_sell_all_threshold

    return data
