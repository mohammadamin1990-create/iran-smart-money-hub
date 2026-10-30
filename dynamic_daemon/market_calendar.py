"""
Tehran Stock Exchange (TSE / Farabourse / Commodity ETFs) Intraday Calendar & Session Detector.
Separates Equity/Leveraged hours (09:00-12:30) from Gold ETF hours (12:00-15:00) and Fixed-Income hours (09:00-15:00).
"""

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone

from dynamic_daemon.jalali import to_shamsi_datetime


TEHRAN_TZ = timezone(timedelta(hours=3, minutes=30))


@dataclass
class MarketSessionState:
    now_tehran: datetime
    is_trading_day: bool
    equity_open: bool
    gold_open: bool
    fixed_income_open: bool
    any_session_active: bool
    session_label: str
    shamsi_datetime: str = ""


class TehranMarketCalendar:
    """
    Determines active trading windows for Iranian market asset classes.
    Trading days: Saturday (5), Sunday (6), Monday (0), Tuesday (1), Wednesday (2).
    """

    TRADING_WEEKDAYS = {5, 6, 0, 1, 2}  # Sat, Sun, Mon, Tue, Wed

    EQUITY_START = time(9, 0)
    EQUITY_END = time(12, 30)

    GOLD_START = time(12, 0)
    GOLD_END = time(15, 0)

    FIXED_INCOME_START = time(9, 0)
    FIXED_INCOME_END = time(15, 0)

    @classmethod
    def now(cls) -> datetime:
        return datetime.now(TEHRAN_TZ)

    @classmethod
    def get_session_state(cls, dt: datetime | None = None, force_open: bool = False) -> MarketSessionState:
        now = dt.astimezone(TEHRAN_TZ) if dt else cls.now()
        shamsi_now = to_shamsi_datetime(now, full_words=True)
        if force_open:
            return MarketSessionState(
                now_tehran=now,
                is_trading_day=True,
                equity_open=True,
                gold_open=True,
                fixed_income_open=True,
                any_session_active=True,
                session_label="شبیه‌سازی / بررسی آزاد تمام بازارها (Force Active)",
                shamsi_datetime=shamsi_now,
            )

        is_day = now.weekday() in cls.TRADING_WEEKDAYS
        t = now.time()

        if not is_day:
            return MarketSessionState(
                now_tehran=now,
                is_trading_day=False,
                equity_open=False,
                gold_open=False,
                fixed_income_open=False,
                any_session_active=False,
                session_label="تعطیل پایان هفته (پنجشنبه / جمعه)",
                shamsi_datetime=shamsi_now,
            )

        eq_open = cls.EQUITY_START <= t <= cls.EQUITY_END
        gold_open = cls.GOLD_START <= t <= cls.GOLD_END
        fi_open = cls.FIXED_INCOME_START <= t <= cls.FIXED_INCOME_END
        any_open = eq_open or gold_open or fi_open

        if eq_open and gold_open:
            label = "همپوشانی بازار سهام، اهرمی و طلا (۱۲:۰۰ تا ۱۲:۳۰)"
        elif eq_open:
            label = "بازار سهام، اهرمی و درآمد ثابت فعال (۰۹:۰۰ تا ۱۲:۰۰)"
        elif gold_open:
            label = "بازار صندوق‌های طلا و درآمد ثابت فعال (۱۲:۳۰ تا ۱۵:۰۰)"
        elif time(8, 45) <= t < cls.EQUITY_START:
            label = "پیش‌گشایش سهام و اهرمی (۰۸:۴۵ تا ۰۹:۰۰)"
        elif time(11, 30) <= t < cls.GOLD_START:
            label = "پیش‌گشایش صندوق‌های طلا"
        else:
            label = "خارج از ساعت معاملات رسمی (بسته)"

        return MarketSessionState(
            now_tehran=now,
            is_trading_day=is_day,
            equity_open=eq_open,
            gold_open=gold_open,
            fixed_income_open=fi_open,
            any_session_active=any_open,
            session_label=label,
            shamsi_datetime=shamsi_now,
        )

    @classmethod
    def is_asset_tradable(cls, asset_class: str, state: MarketSessionState) -> bool:
        if "طلا" in asset_class:
            return state.gold_open
        if "درآمد ثابت" in asset_class:
            return state.fixed_income_open
        return state.equity_open
