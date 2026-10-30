"""
Hybrid Portfolio State Store (مدیریت ترکیبی پرتفوی مجازی خودکار + ثبت دستی خرید/فروش واقعی).
Persists open positions, peak prices (for dynamic Trailing Stops), and closed P&L history.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from typing import Dict, List, Optional

from dynamic_daemon.market_calendar import TehranMarketCalendar
from dynamic_daemon.jalali import to_shamsi_datetime


@dataclass
class PositionRecord:
    symbol: str
    name: str
    asset_class: str
    tracking_mode: str  # "AUTO_VIRTUAL" or "MANUAL_REAL"
    entry_price: float
    peak_price: float
    base_trailing_pct: float
    allocated_toman: float = 0.0
    entry_time: str = ""
    entry_regime: str = ""
    entry_bubble_pct: float = 0.0
    exit_alert_triggered: bool = False
    last_exit_reason: str = ""

    def compute_trailing_stop(self) -> float:
        """
        Computes dynamic trailing stop price from peak_price.
        Once max gain from entry >= +6.0%, tightens trailing stop distance by 0.75x to lock in profits.
        """
        if self.entry_price <= 0 or self.peak_price <= 0:
            return 0.0
        max_gain_pct = ((self.peak_price - self.entry_price) / self.entry_price) * 100.0
        effective_trail = self.base_trailing_pct * 0.75 if max_gain_pct >= 6.0 else self.base_trailing_pct
        return round(self.peak_price * (1.0 - effective_trail / 100.0), 0)

    def current_pnl_pct(self, current_price: float) -> float:
        if self.entry_price <= 0:
            return 0.0
        return round(((current_price - self.entry_price) / self.entry_price) * 100.0, 2)


@dataclass
class ClosedTradeRecord:
    symbol: str
    name: str
    asset_class: str
    tracking_mode: str
    entry_price: float
    exit_price: float
    realized_pnl_pct: float
    allocated_toman: float
    entry_time: str
    exit_time: str
    exit_reason: str


class HybridPositionStore:
    """
    Manages persistent JSON state for both AUTO_VIRTUAL and MANUAL_REAL positions.
    """

    DEFAULT_TRAILING_PCT = {
        "صندوق طلا": 3.0,
        "سهام و حق تقدم": 3.5,
        "صندوق سهامی": 3.5,
        "صندوق اهرمی": 4.5,
        "صندوق درآمد ثابت": 1.5,
    }

    def __init__(self, state_file: Optional[str] = None):
        if state_file is None:
            base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "state"))
            os.makedirs(base_dir, exist_ok=True)
            state_file = os.path.join(base_dir, "portfolio_state.json")
        self.state_file = state_file
        self.positions: Dict[str, PositionRecord] = {}
        self.closed_history: List[ClosedTradeRecord] = []
        self.last_regime: str = ""
        self.load()

    @classmethod
    def default_trail_for(cls, asset_class: str) -> float:
        for k, v in cls.DEFAULT_TRAILING_PCT.items():
            if k in asset_class:
                return v
        return 3.5

    def load(self) -> None:
        if not os.path.exists(self.state_file):
            self.positions = {}
            self.closed_history = []
            self.last_regime = ""
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
            self.last_regime = raw.get("last_regime", "")
            self.positions = {
                sym: PositionRecord(**rec)
                for sym, rec in raw.get("positions", {}).items()
            }
            self.closed_history = [
                ClosedTradeRecord(**c) for c in raw.get("closed_history", [])
            ]
        except Exception as e:
            print(f"Warning: could not load portfolio state ({e}). Starting clean.")

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_file), exist_ok=True)
        now_dt = TehranMarketCalendar.now()
        payload = {
            "updated_at": to_shamsi_datetime(now_dt, full_words=True),
            "updated_at_iso": now_dt.isoformat(),
            "last_regime": self.last_regime,
            "positions": {sym: asdict(pos) for sym, pos in self.positions.items()},
            "closed_history": [asdict(c) for c in self.closed_history[-100:]],
        }
        with open(self.state_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        try:
            from cloud_hub.cloud_state_sync import sync_file_to_cloud_async
            sync_file_to_cloud_async(self.state_file)
        except Exception:
            pass

    def open_virtual_position(
        self,
        symbol: str,
        name: str,
        asset_class: str,
        entry_price: float,
        entry_regime: str = "",
        entry_bubble_pct: float = 0.0,
        allocated_toman: float = 0.0
    ) -> PositionRecord:
        """
        Opens an AUTO_VIRTUAL position when an ENTRY signal triggers (if not already held).
        Never overwrites an existing MANUAL_REAL or AUTO_VIRTUAL position.
        """
        if symbol in self.positions:
            return self.positions[symbol]

        rec = PositionRecord(
            symbol=symbol,
            name=name or symbol,
            asset_class=asset_class,
            tracking_mode="AUTO_VIRTUAL",
            entry_price=entry_price,
            peak_price=entry_price,
            base_trailing_pct=self.default_trail_for(asset_class),
            allocated_toman=allocated_toman,
            entry_time=to_shamsi_datetime(TehranMarketCalendar.now(), full_words=False),
            entry_regime=entry_regime,
            entry_bubble_pct=entry_bubble_pct
        )
        self.positions[symbol] = rec
        self.save()
        return rec

    def register_manual_buy(
        self,
        symbol: str,
        entry_price: float,
        allocated_toman: float = 0.0,
        name: str = "",
        asset_class: str = "سهام و حق تقدم",
        trailing_pct: Optional[float] = None
    ) -> PositionRecord:
        """
        Registers or upgrades a position to MANUAL_REAL with the investor's exact buy price.
        """
        existing = self.positions.get(symbol)
        resolved_name = name or (existing.name if existing else symbol)
        resolved_class = existing.asset_class if (existing and asset_class == "سهام و حق تقدم" and not name) else asset_class
        trail = trailing_pct if trailing_pct is not None else self.default_trail_for(resolved_class)

        rec = PositionRecord(
            symbol=symbol,
            name=resolved_name,
            asset_class=resolved_class,
            tracking_mode="MANUAL_REAL",
            entry_price=entry_price,
            peak_price=entry_price,
            base_trailing_pct=trail,
            allocated_toman=allocated_toman or (existing.allocated_toman if existing else 0.0),
            entry_time=to_shamsi_datetime(TehranMarketCalendar.now(), full_words=False),
            entry_regime=existing.entry_regime if existing else self.last_regime,
            entry_bubble_pct=existing.entry_bubble_pct if existing else 0.0,
            exit_alert_triggered=False,
            last_exit_reason=""
        )
        self.positions[symbol] = rec
        self.save()
        return rec

    def update_market_price(self, symbol: str, current_price: float) -> Optional[PositionRecord]:
        """
        Updates peak_price if current_price sets a new post-entry high.
        """
        pos = self.positions.get(symbol)
        if not pos or current_price <= 0:
            return pos
        if current_price > pos.peak_price:
            pos.peak_price = current_price
            self.save()
        return pos

    def handle_exit_signal(self, symbol: str, exit_price: float, reason: str) -> Optional[ClosedTradeRecord]:
        """
        Handles an automated EXIT signal:
        - If AUTO_VIRTUAL: closes the virtual position automatically and archives P&L.
        - If MANUAL_REAL: marks exit_alert_triggered=True so the investor keeps receiving urgent exit reminders
          until they confirm actual sale via `register_manual_sell`.
        """
        pos = self.positions.get(symbol)
        if not pos:
            return None

        if pos.tracking_mode == "AUTO_VIRTUAL":
            return self.close_position(symbol, exit_price, reason)
        else:
            pos.exit_alert_triggered = True
            pos.last_exit_reason = reason
            self.save()
            return None

    def close_position(self, symbol: str, exit_price: float, reason: str = "خروج دستی") -> Optional[ClosedTradeRecord]:
        pos = self.positions.pop(symbol, None)
        if not pos:
            return None
        pnl = pos.current_pnl_pct(exit_price)
        closed = ClosedTradeRecord(
            symbol=pos.symbol,
            name=pos.name,
            asset_class=pos.asset_class,
            tracking_mode=pos.tracking_mode,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            realized_pnl_pct=pnl,
            allocated_toman=pos.allocated_toman,
            entry_time=pos.entry_time,
            exit_time=to_shamsi_datetime(TehranMarketCalendar.now(), full_words=False),
            exit_reason=reason
        )
        self.closed_history.append(closed)
        self.save()
        return closed
