# upbit-bollinger-squeeze

업비트 원화 마켓을 대상으로 한 변동성 압축 + 볼린저 밴드 신호 봇. 일봉 기준으로 신호를 계산해 텔레그램으로 알린다.

## 설치

```bash
uv venv --python 3.13 .venv && source .venv/bin/activate   # 또는 python3.13 -m venv .venv
pip install -r requirements.txt -r requirements-dev.txt
```

## 실행

```bash
python upbit_main.py                                        # 실시간 모니터링 (기본값, conservative)
python upbit_main.py --strategy balanced                    # 프리셋: conservative | balanced | aggressive
python upbit_main.py --mode backtest --capital 1000000 --days 1095
```

백그라운드 실행 (셸이 리다이렉트 파일을 먼저 열므로 디렉토리를 미리 만든다):

```bash
mkdir -p upbit_output_files/logs
nohup python upbit_main.py > upbit_output_files/logs/nohup.out 2>&1 &
```

텔레그램 알림을 받으려면 `UPBIT_BOLLINGER_TELEGRAM_BOT_TOKEN`과 `UPBIT_BOLLINGER_TELEGRAM_CHAT_ID`를 설정한다. 없으면 알림은 로그에만 남는다.

## 전략과 포지션

- 매수: RSI 70 초과 + 변동성 압축(밴드폭이 최근 50일 중 하위 20%).
- 50% 익절: 진입가 대비 +5%. 전량 매도: 밴드 위치 0.1 이하(하단 밴드).
- 모니터는 매수 알림을 보낸 코인을 `upbit_output_files/positions.json`에 포지션으로 기록하고, 매도 알림은 이 장부에 있는 코인에만 보낸다. 재시작해도 유지된다.
- 텔레그램 명령: `/ticker BTC` 분석, `/status` 상태, `/positions` 열린 포지션, `/close BTC` 실제로 사지 않은 포지션 지우기.

## 개발

```bash
pytest            # 합성 데이터만 사용, 네트워크 없음
ruff format .
ruff check .
```
