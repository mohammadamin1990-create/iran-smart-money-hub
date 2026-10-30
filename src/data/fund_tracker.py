"""
Fund Classifier & Liquidity Migration Tracker for Iranian Capital Market.
Categorizes ETFs into Leveraged, Gold, Fixed-Income, and Equity Funds.
"""

from typing import Dict, List, Optional
import pandas as pd
import numpy as np


class FundTracker:
    """
    Categorizes funds and calculates capital inflows/outflows across macro asset classes.
    """

    # Known Ticker Lists for Iranian ETFs
    LEVERAGED_FUNDS: List[str] = [
        "اهرم", "جهش", "موج", "توان", "شتاب", "نارنج", "بیدار", "دوایکس", "پیشران", "فاتح", "کاریز"
    ]

    GOLD_FUNDS: List[str] = [
        "طلا", "عیار", "کهربا", "زرفام", "گوهر", "زرین", "زر", "تابان", "ناب",
        "نفیس", "جواهر", "گنج", "زرفشان", "مثقال", "گلدا", "دفینه"
    ]

    COMMODITY_CERTIFICATES: List[str] = [
        "طلاس", "شمش", "سکه"
    ]

    FIXED_INCOME_FUNDS: List[str] = [
        "اعتماد", "کاردان", "کمند", "افران", "یاقوت", "پارند", "لبخند", "همای",
        "امین یکم", "سیمرغ", "صپاد", "کاریس", "اونیکس", "نخل", "مانی", "ثابت",
        "آوند", "سردار", "فیروزا", "خاتم", "کیان", "داریک", "سند", "فردا", "پاداش",
        "سامان", "سپید", "ارمغان", "سپهر", "نهال", "گنجینه", "آسام", "امید"
    ]

    EQUITY_FUNDS: List[str] = [
        "پالایش", "دارا یکم", "آگاس", "سرو", "اطلس", "آتیه", "مدیریت", "فراز",
        "فارابی", "افق", "صنام", "توسعه", "آلیا", "کاریس", "دریا", "ثروتمند", "تمشک"
    ]

    @classmethod
    def classify_fund_type(cls, symbol: str, name: str = "", sector_code: str = "") -> str:
        """
        Determines whether a symbol is Leveraged, Gold, Fixed Income, Equity ETF, or Regular Stock.
        """
        clean_symbol = symbol.strip()

        # Check Leveraged
        for lev in cls.LEVERAGED_FUNDS:
            if clean_symbol == lev or clean_symbol.startswith(lev):
                return "صندوق اهرمی"

        # Check Commodity Certificates (Bullion / Coin benchmarks, not Gold ETFs)
        for cert in cls.COMMODITY_CERTIFICATES:
            if clean_symbol == cert or clean_symbol.startswith(cert):
                return "گواهی سپرده کالایی"

        # Check Gold
        for gold in cls.GOLD_FUNDS:
            if clean_symbol == gold or clean_symbol.startswith(gold):
                return "صندوق طلا"

        # Check Fixed Income
        for fi in cls.FIXED_INCOME_FUNDS:
            if clean_symbol == fi or clean_symbol.startswith(fi):
                return "صندوق درآمد ثابت"

        # Check Equity Fund
        for eq in cls.EQUITY_FUNDS:
            if clean_symbol == eq or clean_symbol.startswith(eq):
                return "صندوق سهامی"

        # If it has sector code 68 (ETF) but not matched above, inspect name or fallback
        if sector_code == "68":
            if "درآمد ثابت" in name or "اوراق" in name or "بادرآمد ثابت" in name:
                return "صندوق درآمد ثابت"
            elif "طلا" in name or "فلزات گرانبها" in name or "سکه" in name:
                return "صندوق طلا"
            elif "اهرم" in name or "اهرمی" in name:
                return "صندوق اهرمی"
            return "صندوق سهامی / مختلط"

        return "سهام و حق تقدم"

    @classmethod
    def tag_dataframe(cls, df: pd.DataFrame) -> pd.DataFrame:
        """
        Adds 'asset_class' column to market snapshot DataFrame.
        """
        if df.empty:
            return df

        df = df.copy()
        df["asset_class"] = df.apply(
            lambda row: cls.classify_fund_type(
                str(row.get("symbol", "")),
                str(row.get("name", "")),
                str(row.get("sector_code", ""))
            ),
            axis=1
        )
        return df
