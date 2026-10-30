"""
Dynamic Leverage & Lagging Opportunity Analyzer for Iranian Leveraged Funds (صندوق‌های اهرمی).
Normalizes returns using fund-specific leverage ratios to detect true lagging opportunities (Catch-Up Trades)
and tracks order-book queue locks.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np


@dataclass
class LeveragedFundAnalysis:
    symbol: str
    name: str
    last_price: float
    close_price: float
    pct_change_last: float
    pct_change_close: float
    leverage_ratio: float
    leverage_adjusted_return: float
    adjusted_spread_vs_leader: float
    trade_value_b_toman: float
    p_nav_bubble_pct: float
    net_real_inflow_b_toman: float
    buyer_power_ratio: float
    is_liquid: bool
    is_queue_locked: bool
    catch_up_score: float
    recommendation: str


class LeveragedFundAnalyzer:
    """
    Analyzes leveraged funds using dynamic leverage ratios and queue pressure.
    """

    RIALS_TO_BILLION_TOMAN = 1e10

    # Calibrated effective leverage ratios for Iranian Leveraged ETFs
    DEFAULT_LEVERAGE_MAP: Dict[str, float] = {
        "اهرم": 2.00,
        "شتاب": 1.90,
        "جهش": 1.80,
        "بیدار": 1.70,
        "توان": 1.65,
        "موج": 1.60,
        "نارنج": 1.55,
        "فاتح": 1.50,
    }

    def __init__(self, min_trade_value_b_toman: float = 10.0):
        self.min_trade_value_b_toman = min_trade_value_b_toman

    def get_fund_leverage(self, symbol: str) -> float:
        """Returns the calibrated leverage ratio for a symbol."""
        clean = symbol.strip()
        for k, v in self.DEFAULT_LEVERAGE_MAP.items():
            if clean == k or clean.startswith(k):
                return v
        return 1.60  # Default fallback leverage

    def analyze(self, df: pd.DataFrame, live_leverage_map: Optional[Dict[str, any]] = None) -> List[LeveragedFundAnalysis]:
        """
        Analyzes all leveraged funds, detects leaders, and flags genuine lagging opportunities.
        Uses live Fundbase `real_ratio` when provided.
        """
        import math
        if df.empty:
            return []

        lev_df = df[df.get("asset_class", "") == "صندوق اهرمی"].copy()
        if lev_df.empty:
            return []

        records = []
        for _, row in lev_df.iterrows():
            symbol = str(row.get("symbol", "")).strip()
            name = str(row.get("name", ""))
            last_price = float(row.get("last_price", 0.0))
            close_price = float(row.get("close_price", 0.0))
            max_allowed = float(row.get("max_allowed_price", 0.0))
            pct_last = float(row.get("pct_change_last", 0.0))
            pct_close = float(row.get("pct_change_close", 0.0))
            trade_val = float(row.get("value", 0.0)) / self.RIALS_TO_BILLION_TOMAN
            base_nav = float(row.get("nav", 0.0))
            if base_nav <= 0.0:
                base_nav = float(row.get("yesterday_price", last_price))

            bubble_pct = ((last_price - base_nav) / base_nav * 100.0) if base_nav > 0 else 0.0

            leverage = self.get_fund_leverage(symbol)
            if live_leverage_map:
                fb_m = live_leverage_map.get(symbol)
                if fb_m and getattr(fb_m, "real_ratio", 0.0) > 0:
                    leverage = float(fb_m.real_ratio)

            # Leverage-adjusted return: Return normalized by effective real leverage
            adj_return = (pct_last / max(0.5, leverage)) if leverage > 0 else pct_last

            # Queue lock detection: trading at ceiling (max allowed price or >= +4.8%)
            is_locked = (last_price >= max_allowed > 0) or (pct_last >= 4.8)

            # Money flow
            net_inflow = (
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

            is_liquid = trade_val >= self.min_trade_value_b_toman

            records.append({
                "symbol": symbol,
                "name": name,
                "last_price": last_price,
                "close_price": close_price,
                "pct_change_last": pct_last,
                "pct_change_close": pct_close,
                "leverage_ratio": leverage,
                "adj_return": adj_return,
                "trade_value_b_toman": trade_val,
                "p_nav_bubble_pct": bubble_pct,
                "net_real_inflow_b_toman": net_inflow,
                "buyer_power_ratio": buyer_power,
                "is_liquid": is_liquid,
                "is_queue_locked": is_locked
            })

        if not records:
            return []

        # Find the Leader based on highest leverage-adjusted return among liquid funds
        liquid_records = [r for r in records if r["is_liquid"]]
        leader_record = max(liquid_records, key=lambda r: r["adj_return"]) if liquid_records else max(records, key=lambda r: r["adj_return"])
        leader_adj_return = leader_record["adj_return"]

        analyses: List[LeveragedFundAnalysis] = []
        for r in records:
            spread = leader_adj_return - r["adj_return"]
            is_leader = (r["symbol"] == leader_record["symbol"])

            # Catch-Up Score calculation (0 to 100)
            # High score when: High adjusted spread + Liquid + Low bubble + Good buyer power
            if is_leader:
                score = 90.0 if r["is_queue_locked"] else 80.0
                rec = "🔥 لیدر صعودی بازار" + (" (صف خرید قفل)" if r["is_queue_locked"] else "")
            elif not r["is_liquid"]:
                score = 20.0
                rec = f"⚠️ رد شده به دلیل عدم نقدشوندگی (<{self.min_trade_value_b_toman} همت)"
            else:
                # Calculate genuine catch-up potential using 5 institutional dimensions:
                # 1) Lagging spread, 2) Deep NAV discount, 3) Effective Real Leverage, 4) Buyer Power, 5) Log Liquidity
                spread_pts = min(30.0, max(0.0, spread * 9.0))
                nav_discount_pts = min(25.0, max(-10.0, -r["p_nav_bubble_pct"] * 1.1))
                leverage_efficiency_pts = min(15.0, max(-15.0, (r["leverage_ratio"] - 1.20) * 18.0))
                power_pts = min(15.0, r["buyer_power_ratio"] * 6.0)
                liquidity_pts = min(15.0, math.log10(max(1.0, r["trade_value_b_toman"])) * 5.0)

                score = round(
                    spread_pts + nav_discount_pts + leverage_efficiency_pts + power_pts + liquidity_pts,
                    2
                )

                if spread >= 1.0 and leader_record["is_queue_locked"]:
                    potential_gain = round(spread * r["leverage_ratio"], 1)
                    rec = f"🎯 فرصت طلایی عقب‌افتاده (Catch-up) | پتانسیل جهش: +{potential_gain}%"
                elif spread >= 1.0:
                    rec = f"✅ عقب‌افتاده با پتانسیل رشد تعدیل‌شده (+{spread:.1f}%)"
                else:
                    rec = "همگام با لیدر بازار"

            analyses.append(
                LeveragedFundAnalysis(
                    symbol=r["symbol"],
                    name=r["name"],
                    last_price=r["last_price"],
                    close_price=r["close_price"],
                    pct_change_last=round(r["pct_change_last"], 2),
                    pct_change_close=round(r["pct_change_close"], 2),
                    leverage_ratio=r["leverage_ratio"],
                    leverage_adjusted_return=round(r["adj_return"], 2),
                    adjusted_spread_vs_leader=round(spread, 2),
                    trade_value_b_toman=round(r["trade_value_b_toman"], 1),
                    p_nav_bubble_pct=round(r["p_nav_bubble_pct"], 2),
                    net_real_inflow_b_toman=round(r["net_real_inflow_b_toman"], 2),
                    buyer_power_ratio=round(r["buyer_power_ratio"], 2),
                    is_liquid=r["is_liquid"],
                    is_queue_locked=r["is_queue_locked"],
                    catch_up_score=score,
                    recommendation=rec
                )
            )

        # Sort by catch_up_score descending
        analyses.sort(key=lambda a: a.catch_up_score, reverse=True)
        return analyses
