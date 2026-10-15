# positions.py
"""
모니터가 "매수 알림을 보낸 코인"을 기억하는 포지션 장부.

실제 체결이 아니라 알림 상태를 추적한다. 매수 알림을 보내면 포지션을 열고,
진입가 대비 익절 알림을 보내면 half_sold를 표시하고, 전량 매도 알림을 보내면 닫는다.
경로를 주면 바뀔 때마다 JSON으로 저장해 재시작해도 유지된다. None이면 메모리에만 둔다.
"""

import json
import logging
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Position:
    symbol: str
    entry_price: float
    entry_time: str  # ISO 8601
    half_sold: bool = False

    def gain_pct(self, price: float) -> float:
        return (price / self.entry_price - 1) * 100


class PositionBook:
    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else None
        self._positions: Dict[str, Position] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._positions = {symbol: Position(**fields) for symbol, fields in raw.items()}
            logger.info(f"📌 포지션 {len(self._positions)}개 복원: {self.path}")
        except (OSError, ValueError, TypeError) as e:
            logger.error(f"❌ 포지션 파일을 읽지 못해 빈 장부로 시작합니다 ({self.path}): {e}")
            self._positions = {}

    def _save(self) -> None:
        if not self.path:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {symbol: asdict(p) for symbol, p in self._positions.items()}
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)  # 쓰다 만 파일이 남지 않도록 교체
        except OSError as e:
            logger.error(f"❌ 포지션 저장 실패 ({self.path}): {e}")

    def __len__(self) -> int:
        return len(self._positions)

    def get(self, symbol: str) -> Optional[Position]:
        return self._positions.get(symbol)

    def all(self) -> List[Position]:
        return sorted(self._positions.values(), key=lambda p: p.entry_time)

    def open(self, symbol: str, entry_price: float, when: Optional[datetime] = None) -> Position:
        position = Position(
            symbol, float(entry_price), (when or datetime.now()).isoformat(timespec="seconds")
        )
        self._positions[symbol] = position
        self._save()
        return position

    def mark_half_sold(self, symbol: str) -> Optional[Position]:
        position = self._positions.get(symbol)
        if position is not None:
            position.half_sold = True
            self._save()
        return position

    def close(self, symbol: str) -> Optional[Position]:
        position = self._positions.pop(symbol, None)
        if position is not None:
            self._save()
        return position
