"""
Macro Market Capital Flow & Asset Class Migration Tracker.
Analyzes liquidity rotation between Equities, Leveraged Funds, Gold Funds, and Fixed-Income Funds.
"""

from dataclasses import dataclass
from typing import Dict, List, Any
import pandas as pd
import numpy as np


@dataclass
class AssetClassSummary:
    name: str
    total_trade_value_b_toman: float
    real_buy_value_b_toman: float
    real_sell_value_b_toman: float
    net_real_inflow_b_toman: float
    avg_buyer_power: float
    active_tickers_count: int


@dataclass
class MacroFlowReport:
    asset_summaries: Dict[str, AssetClassSummary]
    market_sentiment: str
    smart_money_verdict: str
    source_asset: str
    destination_asset: str
    total_market_net_real_inflow: float


class MacroFlowAnalyzer:
    """
    Computes aggregated capital rotation across Iranian market asset classes.
    """

    RIALS_TO_BILLION_TOMAN = 1e10
    RIALS_TO_MILLION_TOMAN = 1e7

    def analyze(self, df: pd.DataFrame) -> MacroFlowReport:
        """
        Analyzes tagged DataFrame with asset_class and real/legal trade details.
        """
        if df.empty:
            return MacroFlowReport(
                asset_summaries={},
                market_sentiment="نامشخص (داده‌ای دریافت نشد)",
                smart_money_verdict="بدون داده",
                source_asset="نامشخص",
                destination_asset="نامشخص",
                total_market_net_real_inflow=0.0
            )

        df = df.copy()

        # Compute values in Rials
        # If value column is provided by TSETMC (value in Rials), we use it.
        # Otherwise compute from volume * close_price
        price_col = df["close_price"].where(df["close_price"] > 0, df["last_price"])

        df["real_buy_val_rials"] = df["buy_vol_real"] * price_col
        df["real_sell_val_rials"] = df["sell_vol_real"] * price_col
        df["net_real_inflow_rials"] = df["real_buy_val_rials"] - df["real_sell_val_rials"]

        # Per capita and buyer power
        df["buy_per_capita_m_toman"] = np.where(
            df["buy_count_real"] > 0,
            (df["real_buy_val_rials"] / df["buy_count_real"]) / self.RIALS_TO_MILLION_TOMAN,
            0.0
        )
        df["sell_per_capita_m_toman"] = np.where(
            df["sell_count_real"] > 0,
            (df["real_sell_val_rials"] / df["sell_count_real"]) / self.RIALS_TO_MILLION_TOMAN,
            0.0
        )
        df["buyer_power_ratio"] = np.where(
            df["sell_per_capita_m_toman"] > 0,
            df["buy_per_capita_m_toman"] / df["sell_per_capita_m_toman"],
            1.0
        )

        # Group by asset class
        summaries: Dict[str, AssetClassSummary] = {}
        for asset_class, group in df.groupby("asset_class"):
            tot_val = group["value"].sum() / self.RIALS_TO_BILLION_TOMAN
            real_buy = group["real_buy_val_rials"].sum() / self.RIALS_TO_BILLION_TOMAN
            real_sell = group["real_sell_val_rials"].sum() / self.RIALS_TO_BILLION_TOMAN
            net_inflow = group["net_real_inflow_rials"].sum() / self.RIALS_TO_BILLION_TOMAN

            # Weighted buyer power
            valid_power = group[group["sell_per_capita_m_toman"] > 0]
            avg_power = (
                (valid_power["buyer_power_ratio"] * valid_power["value"]).sum() / valid_power["value"].sum()
                if not valid_power.empty and valid_power["value"].sum() > 0
                else 1.0
            )

            summaries[str(asset_class)] = AssetClassSummary(
                name=str(asset_class),
                total_trade_value_b_toman=round(tot_val, 1),
                real_buy_value_b_toman=round(real_buy, 1),
                real_sell_value_b_toman=round(real_sell, 1),
                net_real_inflow_b_toman=round(net_inflow, 1),
                avg_buyer_power=round(avg_power, 2),
                active_tickers_count=len(group)
            )

        # Diagnose Smart Money Flow Direction (Where money is coming from and going to)
        fi_inflow = summaries.get("صندوق درآمد ثابت", None)
        eq_inflow = summaries.get("سهام و حق تقدم", None)
        lev_inflow = summaries.get("صندوق اهرمی", None)
        gold_inflow = summaries.get("صندوق طلا", None)

        fi_net = fi_inflow.net_real_inflow_b_toman if fi_inflow else 0.0
        eq_net = eq_inflow.net_real_inflow_b_toman if eq_inflow else 0.0
        lev_net = lev_inflow.net_real_inflow_b_toman if lev_inflow else 0.0
        gold_net = gold_inflow.net_real_inflow_b_toman if gold_inflow else 0.0

        equity_risk_appetite = eq_net + lev_net
        total_market_net = sum(s.net_real_inflow_b_toman for s in summaries.values())

        # Determine Origin & Destination
        source = "نقدینگی خارج از بازار / حساب کاربری"
        destination = "نامشخص"

        if fi_net < -10:
            source = "خروج سنگین از صندوق‌های درآمد ثابت (کاهش ریسک‌گریزی)"
        elif eq_net < -20:
            source = "خروج پول حقیقی از سهام و حق تقدم"

        if equity_risk_appetite > 20:
            destination = "ورود به بازار سهام و صندوق‌های اهرمی (ریسک‌پذیری بالا)"
            sentiment = "صعودی پرقدرت (Bullish Risk-On)"
            verdict = (
                f"✅ جریان هوشمند فعال: نقدینگی با قدرت ({equity_risk_appetite:+.1f} میلیارد تومان) "
                f"وارد سهام و صندوق‌های اهرمی شده است. پتانسیل نوسان‌گیری ۱ تا ۳ روزه بالاست."
            )
        elif gold_net > 20 and equity_risk_appetite <= 0:
            destination = "ورود به صندوق‌های طلا و ابزارهای مبتنی بر طلا/ارز"
            sentiment = "پناه بردن به طلا (Hedge / Gold Rally)"
            verdict = (
                f"⚠️ مهاجرت پول به طلا: پول حقیقی با حجم ({gold_net:+.1f} میلیارد تومان) "
                f"به سمت صندوق‌های طلا حرکت کرده است. سهام پرریسک محسوب می‌شود."
            )
        elif fi_net > 30 and equity_risk_appetite < -15:
            destination = "پارک در صندوق‌های درآمد ثابت (ریسک‌گریزی و احتیاط)"
            sentiment = "نزولی / احتیاط کامل (Risk-Off Defensive)"
            verdict = (
                f"🛑 خروج پول از سهام ({eq_net:+.1f} همت) و پارک در درآمد ثابت ({fi_net:+.1f} همت). "
                f"استراتژی مناسب: حفظ وجه نقد در درآمد ثابت و پرهیز از خریدهای نوسانی."
            )
        else:
            destination = "توزیع متعادل / نوسان محدود"
            sentiment = "خنثی / رنج (Neutral)"
            verdict = (
                f"⚖️ بازار در حالت تعادل نسبی: خالص ورود به سهام {equity_risk_appetite:+.1f} م.ت. "
                f"انتخاب سهام باید با دقت و صرفاً روی نمادهای تک با سرانه خرید استثنایی باشد."
            )

        return MacroFlowReport(
            asset_summaries=summaries,
            market_sentiment=sentiment,
            smart_money_verdict=verdict,
            source_asset=source,
            destination_asset=destination,
            total_market_net_real_inflow=round(total_market_net, 1)
        )
