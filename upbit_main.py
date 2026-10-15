"""
업비트 코인 변동성 폭파 볼린저 밴드 트레이딩 시스템 - 메인 실행 파일

사용법:
    python upbit_main.py                                   # 실시간 모니터링 (기본값)
    python upbit_main.py --mode monitor --strategy balanced
    python upbit_main.py --mode backtest --capital 1000000 --days 1095

텔레그램 설정 (모니터링 모드):
    export UPBIT_BOLLINGER_TELEGRAM_BOT_TOKEN="your_bot_token"
    export UPBIT_BOLLINGER_TELEGRAM_CHAT_ID="your_chat_id"
"""

import argparse
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from positions import PositionBook
from strategy import STRATEGY_PRESETS, StrategyParams
from upbit_realtime_monitor import DEFAULT_POSITIONS_PATH, UpbitRealTimeVolatilityMonitor

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "upbit_output_files" / "logs"
# 모니터의 상태 메시지에 "5분"이 문자열로 박혀 있다. 바꾸려면 모니터도 같이 고쳐야 한다.
SCAN_INTERVAL = 300

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="업비트 변동성 폭파 볼린저 밴드 트레이딩 시스템")
    parser.add_argument(
        "--mode",
        default="monitor",
        choices=["monitor", "backtest", "monitor-default"],
        help="monitor: 실시간 모니터링 (기본값), backtest: 백테스트. monitor-default는 monitor의 이전 이름",
    )
    parser.add_argument(
        "--strategy",
        default="conservative",
        choices=list(STRATEGY_PRESETS),
        help="전략 프리셋 (기본값: conservative)",
    )
    backtest = parser.add_argument_group("backtest 모드 옵션")
    backtest.add_argument(
        "--capital", type=float, default=1_000_000, help="초기 자금 (원, 기본값: 1,000,000)"
    )
    backtest.add_argument(
        "--days", type=int, default=1095, help="분석 기간 (일, 기본값: 1095 = 약 3년)"
    )
    return parser


def parse_args(argv=None) -> argparse.Namespace:
    args = build_parser().parse_args(argv)
    if args.mode == "monitor-default":
        args.mode = "monitor"
    return args


def setup_logging(log_dir: Path) -> Path:
    """파일 + 콘솔 로깅. 로그 디렉토리가 없으면 만든다."""
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"upbit_monitor_{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[logging.FileHandler(log_file, encoding="utf-8"), logging.StreamHandler()],
    )
    # 텔레그램 폴링이 1초마다 httpx 요청을 만든다. INFO로 두면 로그가 그걸로 가득 찬다.
    for noisy in ("httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file


def print_banner(mode: str, params: StrategyParams) -> None:
    print("🚀==============================================================================🚀")
    print("     업비트 코인 변동성 폭파 볼린저 밴드 트레이딩 시스템")
    print("🚀==============================================================================🚀")
    print(f"⚙️ 실행 모드: {mode.upper()}")
    print(f"🎯 전략: {params.label}")
    print(f"📅 시작 시간: {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"🐍 Python 버전: {sys.version.split()[0]}")
    print("=" * 80)


def run_monitor(params: StrategyParams) -> int:
    log_file = setup_logging(LOG_DIR)
    telegram_bot_token = os.getenv("UPBIT_BOLLINGER_TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("UPBIT_BOLLINGER_TELEGRAM_CHAT_ID")
    monitor = UpbitRealTimeVolatilityMonitor(
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        params=params,
        positions=PositionBook(DEFAULT_POSITIONS_PATH),
    )

    print(f"""🎯 백그라운드 모니터링 설정:
   📊 감시 코인: {len(monitor.watchlist)}개 (업비트 원화 마켓)
   ⏰ 스캔 간격: {SCAN_INTERVAL // 60}분
   📱 텔레그램 알림: {"활성화" if telegram_bot_token else "비활성화"}
   🟢 24시간 거래 모니터링
   📝 로그 파일: {log_file.relative_to(BASE_DIR)}
   📌 포지션 파일: {DEFAULT_POSITIONS_PATH.relative_to(BASE_DIR)} (열린 포지션 {len(monitor.positions)}개)
   🔄 오류 발생시 자동 재시도
   🤖 텔레그램 명령어: /ticker, /status, /positions, /close, /start
   ⏹️ 종료: kill -TERM [PID] 또는 Ctrl+C""")
    print("=" * 80)
    logger.info(
        f"업비트 백그라운드 모니터링 시작 (전략: {params.label}, 스캔 간격: {SCAN_INTERVAL}초)"
    )

    try:
        # 모니터링 스레드를 join하므로 중지될 때까지 돌아오지 않는다.
        monitor.start_monitoring(scan_interval=SCAN_INTERVAL)
    except Exception as e:
        logger.error(f"모니터링 실패: {e}", exc_info=True)
        monitor.stop_monitoring()
        return 1
    return 0


def run_backtest(strategy_mode: str, capital: float, days: int) -> int:
    # matplotlib 임포트가 딸려 오므로 모니터 모드에서는 불러오지 않는다.
    from upbit_backtest_strategy import UpbitVolatilityBollingerBacktest

    backtest = UpbitVolatilityBollingerBacktest(
        initial_capital=capital, strategy_mode=strategy_mode
    )
    results = backtest.run_comprehensive_analysis(
        days=days, max_cryptos=15, detailed_analysis="top3", save_charts=True
    )
    if not results:
        print("❌ 분석 실패: 분석 가능한 코인이 없습니다.")
        return 1

    print("\n🏆 수익률 상위 3개 코인:")
    for rank, (_, row) in enumerate(results["summary_results"].head(3).iterrows(), start=1):
        print(f"{rank}. {row['Symbol']}: {row['Total_Return(%)']}%")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    params = StrategyParams.from_mode(args.strategy)
    print_banner(args.mode, params)
    if args.mode == "monitor":
        return run_monitor(params)
    return run_backtest(args.strategy, args.capital, args.days)


if __name__ == "__main__":
    sys.exit(main())
