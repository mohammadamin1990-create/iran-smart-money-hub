"""
Synthetic Live NAV & Valuation Engine for Iranian Gold Funds (صندوق‌های طلا).
Solves the delayed official TSETMC NAV problem by computing real-time Synthetic NAV
benchmarked against live gold bullion deposit certificates (گواهی سپرده شمش طلا).
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np


@dataclass
class GoldFundValuation:
    symbol: str
    name: str
    last_price: float
    close_price: float
    pct_change_last: float
    trade_value_b_toman: float
    official_nav: float
    synthetic_nav: float
    official_bubble_pct: float
    synthetic_bubble_pct: float
    net_real_inflow_b_toman: float
    buyer_power_ratio: float
    valuation_status: str
    is_liquid: bool
    verdict: str
    # Deep Fundbase metrics
    inherent_bubble_pct: Optional[float] = None
    total_bubble_pct: Optional[float] = None
    gold_bar_bubble_pct: Optional[float] = None
    gold_coin_bubble_pct: Optional[float] = None
    bar_pct: Optional[float] = None
    coin_pct: Optional[float] = None
    remained_capacity: Optional[float] = None


class GoldSyntheticNAVEngine:
    """
    Computes real-time synthetic NAV and true bubble for Iranian gold funds.
    """

    RIALS_TO_BILLION_TOMAN = 1e10

    # Typical portfolio composition of gold ETFs: ~95% gold certificates + ~5% cash/fixed income
    GOLD_WEIGHT = 0.95
    CASH_WEIGHT = 0.05

    def __init__(self, min_trade_value_b_toman: float = 10.0):
        self.min_trade_value_b_toman = min_trade_value_b_toman

    def calculate_valuations(
        self,
        df: pd.DataFrame,
        spot_gold_change_pct: float = 0.0,
        spot_gold_symbol: str = "طلاس"
    ) -> List[GoldFundValuation]:
        """
        Calculates synthetic NAV and bubble metrics for all gold funds.

        Args:
            df: Market snapshot DataFrame containing fund data.
            spot_gold_change_pct: Intraday % change of spot gold bullion certificate.
                                  If 0.0, engine attempts to infer it from the gold bullion ticker.
            spot_gold_symbol: Symbol of gold deposit certificate (e.g. CD3000 / طلاس / شمش).
        """
        if df.empty:
            return []

        # Filter gold funds
        gold_df = df[df.get("asset_class", "") == "صندوق طلا"].copy()
        if gold_df.empty:
            return []

        # If spot gold change is not explicitly provided, estimate from the lowest-lag gold certificate
        if spot_gold_change_pct == 0.0:
            cert = df[df["symbol"].str.contains("طلاس|شمش|CD3000", na=False)]
            if not cert.empty:
                spot_gold_change_pct = float(cert.iloc[0].get("pct_change_last", 0.0))

        valuations: List[GoldFundValuation] = []

        for _, row in gold_df.iterrows():
            symbol = str(row.get("symbol", ""))
            name = str(row.get("name", ""))
            last_price = float(row.get("last_price", 0.0))
            close_price = float(row.get("close_price", 0.0))
            pct_change_last = float(row.get("pct_change_last", 0.0))
            trade_val_b_toman = float(row.get("value", 0.0)) / self.RIALS_TO_BILLION_TOMAN

            # In TSETMC, yesterday_price is roughly the baseline for official NAV if live NAV is unupdated
            # or extracted from nav field
            base_nav = float(row.get("nav", 0.0))
            if base_nav <= 0.0:
                base_nav = float(row.get("yesterday_price", last_price))

            # 1. Official Bubble (often lagged)
            official_bubble = ((last_price - base_nav) / base_nav * 100.0) if base_nav > 0 else 0.0

            # 2. Synthetic Live NAV: Updates base NAV with live spot gold return
            # Synthetic_NAV = Base_NAV * (1 + (Gold_Weight * Spot_Gold_Change) / 100)
            synthetic_nav = base_nav * (1.0 + (self.GOLD_WEIGHT * spot_gold_change_pct / 100.0))
            synthetic_bubble = ((last_price - synthetic_nav) / synthetic_nav * 100.0) if synthetic_nav > 0 else 0.0

            # Real/Legal money metrics
            net_real_inflow = (
                (float(row.get("buy_vol_real", 0.0)) - float(row.get("sell_vol_real", 0.0))) * close_price
            ) / self.RIALS_TO_BILLION_TOMAN

            buy_per_capita = (
                float(row.get("buy_vol_real", 0.0)) * close_price / float(row.get("buy_count_real", 1))
                if float(row.get("buy_count_real", 0)) > 0 else 0.0
            )
            sell_per_capita = (
                float(row.get("sell_vol_real", 0.0)) * close_price / float(row.get("sell_count_real", 1))
                if float(row.get("sell_count_real", 0)) > 0 else 0.0
            )
            buyer_power = (buy_per_capita / sell_per_capita) if sell_per_capita > 0 else 1.0

            is_liquid = trade_val_b_toman >= self.min_trade_value_b_toman

            # Valuation Status Classification
            if synthetic_bubble <= 1.5:
                status = "🟢 ارزان و ارزنده (Undervalued)"
                verdict = "حباب نزدیک به صفر یا منفی؛ فرصت ورود کم‌ریسک"
            elif synthetic_bubble <= 6.0:
                status = "⚪ منصفانه و نرمال (Fair)"
                verdict = "حباب در محدوده متعادل بازار"
            elif synthetic_bubble <= 10.0:
                status = "🟡 حباب نسبتاً بالا (Elevated)"
                verdict = "نیازمند احتیاط؛ احتمال توقف موقت رشد"
            else:
                status = "🔴 حباب هیجانی و خطرناک (Overheated)"
                verdict = f"حباب بحرانی ({synthetic_bubble:+.1f}%)؛ ریسک بالای اصلاح و ریزش حباب"

            if not is_liquid:
                verdict += f" | ⚠️ ارزش معاملات پایین (<{self.min_trade_value_b_toman} همت)"

            valuations.append(
                GoldFundValuation(
                    symbol=symbol,
                    name=name,
                    last_price=last_price,
                    close_price=close_price,
                    pct_change_last=round(pct_change_last, 2),
                    trade_value_b_toman=round(trade_val_b_toman, 1),
                    official_nav=round(base_nav, 0),
                    synthetic_nav=round(synthetic_nav, 0),
                    official_bubble_pct=round(official_bubble, 2),
                    synthetic_bubble_pct=round(synthetic_bubble, 2),
                    net_real_inflow_b_toman=round(net_real_inflow, 2),
                    buyer_power_ratio=round(buyer_power, 2),
                    valuation_status=status,
                    is_liquid=is_liquid,
                    verdict=verdict
                )
            )

        # Sort by synthetic bubble ascending (lowest bubble first)
        valuations.sort(key=lambda v: v.synthetic_bubble_pct)
        return valuations

    def enrich_with_fundbase(
        self,
        valuations: List[GoldFundValuation],
        fundbase_metrics: Dict[str, any]
    ) -> List[GoldFundValuation]:
        """
        Enriches live valuations with deep metrics from Fundbase (triple bubble, composition, capacity).
        """
        for v in valuations:
            m = fundbase_metrics.get(v.symbol)
            if not m:
                # Try finding by partial match
                for sym, met in fundbase_metrics.items():
                    if sym in v.symbol or v.symbol in sym or sym in v.name:
                        m = met
                        break
            if m:
                v.inherent_bubble_pct = getattr(m, "inherent_bubble", None)
                v.total_bubble_pct = getattr(m, "total_bubble", None)
                v.gold_bar_bubble_pct = getattr(m, "gold_bar_bubble", None)
                v.gold_coin_bubble_pct = getattr(m, "gold_coin_bubble", None)
                v.bar_pct = getattr(m, "bar_pct", None)
                v.coin_pct = getattr(m, "coin_pct", None)
                v.remained_capacity = getattr(m, "remained_capacity", None)

                # Enhance verdict if issuance capacity is critically low (< 5%)
                if v.remained_capacity is not None and v.remained_capacity < 5.0:
                    v.verdict += f" | ⚠️ ظرفیت صدور رو به اتمام ({v.remained_capacity:.1f}%)؛ ریسک انبساط حباب"
        return valuations

    def pick_best_gold_fund(self, valuations: List[GoldFundValuation]) -> Optional[GoldFundValuation]:
        """
        Picks the #1 most attractive gold fund:
        Must be liquid, have lowest synthetic bubble, and positive or neutral smart money flow.
        """
        liquid_funds = [v for v in valuations if v.is_liquid]
        if not liquid_funds:
            return None

        # Filter out overheated bubble funds (> 8%)
        safe_funds = [v for v in liquid_funds if v.synthetic_bubble_pct <= 8.0]
        if not safe_funds:
            # Fallback to the one with the lowest bubble among liquid ones
            return min(liquid_funds, key=lambda v: v.synthetic_bubble_pct)

        # Score based on: Low total/synthetic bubble + Market-maker depth + Bullion bar purity + Smart money flow
        import math
        def score_fund(v: GoldFundValuation) -> float:
            effective_bubble = v.total_bubble_pct if v.total_bubble_pct is not None else v.synthetic_bubble_pct
            bubble_term = -max(-2.0, effective_bubble) * 2.0
            power_bonus = min(20.0, v.buyer_power_ratio * 5.0)
            inflow_bonus = min(20.0, max(0.0, v.net_real_inflow_b_toman) * 2.0)
            depth_bonus = min(14.0, math.log10(max(1.0, v.trade_value_b_toman)) * 4.0)
            bar_bonus = ((v.bar_pct / 100.0) * 6.0) if v.bar_pct is not None else 0.0
            cap_penalty = 15.0 if (v.remained_capacity is not None and v.remained_capacity < 5.0) else 0.0
            return 100.0 + bubble_term + power_bonus + inflow_bonus + depth_bonus + bar_bonus - cap_penalty

        return max(safe_funds, key=score_fund)
