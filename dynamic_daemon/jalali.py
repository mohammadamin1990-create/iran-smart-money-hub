"""
High-Precision Jalali (Solar Hijri / تقویم شمسی) Date Conversion & Formatting Module.
Pure-Python, zero external dependencies.
"""

from datetime import datetime
from typing import Tuple, Union


PERSIAN_MONTH_NAMES = [
    "",
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]

PERSIAN_WEEKDAY_NAMES = {
    5: "شنبه",
    6: "یک‌شنبه",
    0: "دوشنبه",
    1: "سه‌شنبه",
    2: "چهارشنبه",
    3: "پنج‌شنبه",
    4: "جمعه",
}


def gregorian_to_jalali(gy: int, gm: int, gd: int) -> Tuple[int, int, int]:
    """Converts a Gregorian date (year, month, day) to Jalali (Solar Hijri)."""
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    if gy > 1600:
        jy = 979
        gy -= 1600
    else:
        jy = 0
        gy -= 621
    gy2 = gy if gm > 2 else gy - 1
    days = 365 * gy + (gy2 + 3) // 4 - (gy2 + 99) // 100 + (gy2 + 399) // 400 - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    if days < 186:
        jm = 1 + days // 31
        jd = 1 + days % 31
    else:
        jm = 7 + (days - 186) // 30
        jd = 1 + (days - 186) % 30
    return jy, jm, jd


def to_shamsi_date(dt: datetime) -> str:
    """Returns compact Shamsi date: '1405/08/08'."""
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    return f"{jy:04d}/{jm:02d}/{jd:02d}"


def to_shamsi_datetime(dt: datetime, full_words: bool = False, include_seconds: bool = False) -> str:
    """
    Formats datetime in Solar Hijri:
    - compact: '1405/08/08 23:25'
    - full_words: 'جمعه ۸ آبان ۱۴۰۵ - ساعت ۲۳:۲۵'
    """
    jy, jm, jd = gregorian_to_jalali(dt.year, dt.month, dt.day)
    t_str = dt.strftime("%H:%M:%S" if include_seconds else "%H:%M")
    if full_words:
        w_name = PERSIAN_WEEKDAY_NAMES.get(dt.weekday(), "")
        m_name = PERSIAN_MONTH_NAMES[jm]
        return f"{w_name} {jd} {m_name} {jy} - ساعت {t_str}"
    return f"{jy:04d}/{jm:02d}/{jd:02d} {t_str}"


def iso_or_str_to_shamsi(date_str: str, full_words: bool = False) -> str:
    """
    Parses an ISO or 'YYYY-MM-DD HH:MM' string and converts to Shamsi.
    If already Shamsi (starting with '140'), returns as-is.
    """
    if not date_str:
        return ""
    s = str(date_str).strip()
    if s.startswith("140") or "آبان" in s or "مهر" in s:
        return s
    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s[:19], fmt)
            return to_shamsi_datetime(dt, full_words=full_words, include_seconds=len(s) > 16 and ":" in s[16:])
        except ValueError:
            pass
    return s
