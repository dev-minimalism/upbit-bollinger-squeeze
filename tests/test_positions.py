"""PositionBook: 열기/절반 익절/닫기와 파일 영속성."""

import json
from datetime import datetime

import pytest

from positions import Position, PositionBook


def test_in_memory_book_round_trip():
    book = PositionBook(None)
    assert len(book) == 0 and book.get("KRW-BTC") is None
    opened = book.open("KRW-BTC", 100.0, datetime(2026, 10, 15, 9, 0))
    assert opened == Position("KRW-BTC", 100.0, "2026-10-15T09:00:00")
    assert book.mark_half_sold("KRW-BTC").half_sold
    assert book.close("KRW-BTC") is opened
    assert len(book) == 0
    assert book.close("KRW-BTC") is None and book.mark_half_sold("KRW-BTC") is None


def test_gain_pct_is_relative_to_entry():
    assert Position("KRW-BTC", 100.0, "t").gain_pct(105.0) == pytest.approx(5.0)
    assert Position("KRW-BTC", 200.0, "t").gain_pct(150.0) == pytest.approx(-25.0)


def test_all_is_sorted_by_entry_time():
    book = PositionBook(None)
    book.open("KRW-ETH", 1.0, datetime(2026, 1, 2))
    book.open("KRW-BTC", 1.0, datetime(2026, 1, 1))
    assert [p.symbol for p in book.all()] == ["KRW-BTC", "KRW-ETH"]


def test_changes_are_persisted_and_reloaded(tmp_path):
    path = tmp_path / "out" / "positions.json"  # 상위 디렉토리가 없어도 만든다
    book = PositionBook(path)
    book.open("KRW-BTC", 100.0, datetime(2026, 10, 15))
    book.open("KRW-ETH", 50.0, datetime(2026, 10, 16))
    book.mark_half_sold("KRW-BTC")
    book.close("KRW-ETH")

    reloaded = PositionBook(path)
    assert [p.symbol for p in reloaded.all()] == ["KRW-BTC"]
    assert reloaded.get("KRW-BTC").half_sold and reloaded.get("KRW-BTC").entry_price == 100.0
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "KRW-BTC": {
            "symbol": "KRW-BTC",
            "entry_price": 100.0,
            "entry_time": "2026-10-15T00:00:00",
            "half_sold": True,
        }
    }
    assert not path.with_suffix(".tmp").exists()


def test_corrupt_file_starts_empty_without_raising(tmp_path):
    path = tmp_path / "positions.json"
    path.write_text("{not json", encoding="utf-8")
    book = PositionBook(path)
    assert len(book) == 0
    book.open("KRW-BTC", 1.0)  # 덮어쓸 수 있어야 한다
    assert PositionBook(path).get("KRW-BTC") is not None
