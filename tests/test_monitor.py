"""모니터의 오프라인 동작: 감시 목록, 알림 메시지, 쿨다운. 텔레그램과 pyupbit는 호출하지 않는다."""

import time
from datetime import datetime

import pytest

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


def test_without_a_token_alerts_are_logged_and_count_as_sent(monitor):
    # 텔레그램이 없어도 포지션 장부가 똑같이 움직이는 드라이런이 되도록 성공으로 친다.
    assert monitor.send_telegram_alert("hello") is True


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


@pytest.fixture
def sending(monitor, monkeypatch):
    """텔레그램 전송을 성공으로 흉내 내고 보낸 메시지를 모은다."""
    sent = []
    monkeypatch.setattr(
        monitor,
        "send_telegram_alert",
        lambda message, parse_mode="HTML": sent.append(message) or True,
    )
    return monitor, sent


def test_buy_alert_opens_a_position_and_blocks_further_buys(sending):
    monitor, sent = sending
    assert monitor.process_signals(_signals(price=100.0)) is True
    position = monitor.positions.get("KRW-BTC")
    assert position is not None and position.entry_price == 100.0 and not position.half_sold
    assert "비트코인" in sent[0] and "익절 목표" in sent[0] and "105원" in sent[0]
    # 포지션이 열려 있는 동안 추가 매수 알림은 없다
    assert monitor.process_signals(_signals(price=101.0)) is False
    assert len(sent) == 1


def test_sell_alerts_only_for_coins_with_a_position(sending):
    monitor, sent = sending
    signals = _signals("KRW-ETH", buy_signal=False, sell_50_signal=True, sell_all_signal=True)
    assert monitor.process_signals(signals) is False
    assert sent == []


def test_take_profit_alert_once_then_sell_all_closes_the_position(sending):
    monitor, sent = sending
    monitor.process_signals(_signals(price=100.0))  # 매수, 진입가 100
    assert monitor.process_signals(_signals(price=104.0, buy_signal=False)) is False  # +4%: 아직
    assert monitor.process_signals(_signals(price=105.0, buy_signal=False)) is True  # +5%
    assert monitor.positions.get("KRW-BTC").half_sold
    assert "50% 익절" in sent[-1] and "+5.0%" in sent[-1]
    # 절반 익절은 한 번만
    assert monitor.process_signals(_signals(price=120.0, buy_signal=False)) is False
    # 하단 밴드 신호 -> 전량 매도 알림, 포지션 닫힘
    assert (
        monitor.process_signals(_signals(price=90.0, buy_signal=False, sell_all_signal=True))
        is True
    )
    assert monitor.positions.get("KRW-BTC") is None
    assert "전량 매도" in sent[-1] and "-10.0%" in sent[-1] and "절반은 이미 익절" in sent[-1]
    assert monitor.total_signals_sent == 3


def test_sell_all_before_take_profit_closes_the_position(sending):
    monitor, sent = sending
    monitor.process_signals(_signals(price=100.0))
    assert (
        monitor.process_signals(_signals(price=80.0, buy_signal=False, sell_all_signal=True))
        is True
    )
    assert monitor.positions.get("KRW-BTC") is None
    assert "-20.0%" in sent[-1] and "절반은 이미 익절" not in sent[-1]


def test_indicator_half_exit_signal_also_counts_with_a_position(sending):
    monitor, sent = sending
    monitor.process_signals(_signals(price=100.0))
    assert (
        monitor.process_signals(_signals(price=101.0, buy_signal=False, sell_50_signal=True))
        is True
    )
    assert monitor.positions.get("KRW-BTC").half_sold


def test_failed_send_leaves_the_book_and_cooldown_untouched(monitor, monkeypatch):
    monkeypatch.setattr(monitor, "send_telegram_alert", lambda message, parse_mode="HTML": False)
    assert monitor.process_signals(_signals(price=100.0)) is False
    assert monitor.positions.get("KRW-BTC") is None
    assert monitor.total_signals_sent == 0 and monitor.last_signal_time is None

    # 전송이 되기 시작하면 같은 신호가 그대로 나간다 (실패한 알림은 억제되지 않는다)
    sent = []
    monkeypatch.setattr(
        monitor,
        "send_telegram_alert",
        lambda message, parse_mode="HTML": sent.append(message) or True,
    )
    assert monitor.process_signals(_signals(price=100.0)) is True
    assert monitor.positions.get("KRW-BTC").entry_price == 100.0

    # 익절 전송 실패 -> half_sold 안 됨 -> 다음 스캔에서 다시 시도
    monkeypatch.setattr(monitor, "send_telegram_alert", lambda message, parse_mode="HTML": False)
    assert monitor.process_signals(_signals(price=106.0, buy_signal=False)) is False
    assert not monitor.positions.get("KRW-BTC").half_sold


def test_reentry_after_close_respects_the_buy_cooldown(sending, monkeypatch):
    monitor, sent = sending
    now = [1_000_000.0]
    monkeypatch.setattr(time, "time", lambda: now[0])
    monitor.process_signals(_signals(price=100.0))
    monitor.positions.close("KRW-BTC")  # /close 로 지운 상황
    assert (
        monitor.process_signals(_signals(price=100.0)) is False
    )  # 1시간 안에는 다시 알리지 않는다
    now[0] += monitor.alert_cooldown
    assert monitor.process_signals(_signals(price=100.0)) is True
