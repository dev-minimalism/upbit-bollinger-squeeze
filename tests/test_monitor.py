"""모니터의 오프라인 동작: 감시 목록, 알림 메시지, 쿨다운. 텔레그램과 pyupbit는 호출하지 않는다."""

import time
from datetime import datetime

from upbit_realtime_monitor import WATCHLIST


def _signals(symbol="KRW-BTC", **overrides):
    base = dict(
        symbol=symbol,
        price=100_000_000.0,
        rsi=72.5,
        bb_position=0.35,
        band_width=0.05,
        volatility_squeeze=True,
        buy_signal=True,
        sell_50_signal=False,
        sell_all_signal=False,
        timestamp=datetime(2026, 10, 15, 9, 0),
    )
    base.update(overrides)
    return base


def test_watchlist_is_derived_from_the_single_mapping(monitor):
    assert monitor.watchlist == list(WATCHLIST)
    assert all(ticker.startswith("KRW-") for ticker in WATCHLIST)
    assert all(WATCHLIST.values())


def test_add_and_remove_touch_the_instance_only(monitor):
    monitor.add_to_watchlist(["NEWCOIN"])  # KRW- 접두어가 없으면 붙여준다
    assert monitor.watchlist[-1] == "KRW-NEWCOIN"
    assert "KRW-NEWCOIN" not in WATCHLIST
    monitor.remove_from_watchlist(["KRW-NEWCOIN"])
    assert "KRW-NEWCOIN" not in monitor.watchlist
    assert monitor.watchlist == list(WATCHLIST)


def test_alert_message_uses_korean_name_and_falls_back_to_ticker(monitor):
    message = monitor.format_alert_message(_signals("KRW-BTC"), "buy")
    assert "비트코인" in message and "KRW-BTC" in message
    message = monitor.format_alert_message(_signals("KRW-UNLISTED"), "buy")
    assert "KRW-UNLISTED" in message


def test_without_a_token_alerts_are_only_logged(monitor):
    assert monitor.send_telegram_alert("hello") is False


def test_cooldown_is_per_symbol_and_signal_type(monitor, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])

    assert monitor.should_send_alert("KRW-BTC", "buy")
    monitor._mark_alert_sent("KRW-BTC", "buy")
    assert not monitor.should_send_alert("KRW-BTC", "buy")
    assert monitor.should_send_alert("KRW-BTC", "sell_50")
    assert monitor.should_send_alert("KRW-ETH", "buy")

    now[0] += monitor.alert_cooldown
    assert monitor.should_send_alert("KRW-BTC", "buy")


def test_cooldown_starts_only_after_a_successful_send(monitor, monkeypatch):
    sent = []
    monkeypatch.setattr(monitor, "send_telegram_alert", lambda message, parse_mode="HTML": False)
    assert monitor.process_signals(_signals()) is False
    assert monitor.total_signals_sent == 0
    assert monitor.last_signal_time is None

    # 전송이 실패했던 알림은 억제되지 않고 다음 스캔에서 다시 나간다.
    monkeypatch.setattr(
        monitor,
        "send_telegram_alert",
        lambda message, parse_mode="HTML": sent.append(message) or True,
    )
    assert monitor.process_signals(_signals()) is True
    assert monitor.total_signals_sent == 1 and len(sent) == 1
    assert "비트코인" in sent[0]

    # 이제는 쿨다운 안이라 같은 신호가 다시 나가지 않는다.
    assert monitor.process_signals(_signals()) is False
    assert len(sent) == 1


def test_each_active_signal_type_is_sent_separately(monitor, monkeypatch):
    sent = []
    monkeypatch.setattr(
        monitor,
        "send_telegram_alert",
        lambda message, parse_mode="HTML": sent.append(message) or True,
    )
    monitor.process_signals(_signals(buy_signal=True, sell_50_signal=True, sell_all_signal=False))
    assert len(sent) == 2
    assert "매수 신호" in sent[0] and "50% 익절" in sent[1]
    assert monitor.total_signals_sent == 2
