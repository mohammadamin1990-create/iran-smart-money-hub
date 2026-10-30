"""
Stock-Level Smart Money Screener & Composite Scoring Engine.
Identifies individual tickers with extreme smart money accumulation, buyer power, and volume anomalies.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np


@dataclass
class SmartMoneyCandidate:
    symbol: str
    name: str
    sector_name: str
    close_price: float
    pct_change_close: float
    pct_change_last: float
    total_trade_value_b_toman: float
    net_real_inflow_b_toman: float
    buy_per_capita_m_toman: float
    sell_per_capita_m_toman: float
    buyer_power_ratio: float
    volume_to_base_ratio: float
    smart_money_score: float
    signal_strength: str
    rationale: str


class SmartMoneyScreener:
    """
    Screens market snapshot for high-probability smart money accumulation candidates.
    """

    RIALS_TO_BILLION_TOMAN = 1e10
    RIALS_TO_MILLION_TOMAN = 1e7

    def __init__(
        self,
        min_trade_value_b_toman: float = 0.5,
        min_buyer_power: float = 1.3,
        min_buy_per_capita_m_toman: float = 25.0,
        min_net_inflow_b_toman: float = 0.1
    ):
        self.min_trade_value_b_toman = min_trade_value_b_toman
        self.min_buyer_power = min_buyer_power
        self.min_buy_per_capita_m_toman = min_buy_per_capita_m_toman
        self.min_net_inflow_b_toman = min_net_inflow_b_toman

    def screen(
        self,
        df: pd.DataFrame,
        top_sectors: Optional[List[str]] = None
    ) -> List[SmartMoneyCandidate]:
        """
        Filters and ranks stocks based on Smart Money metrics.
        """
        if df.empty:
            return []

        df = df.copy()

        # Only evaluate equities & leveraged ETFs
        allowed_assets = ["سهام و حق تقدم", "صندوق اهرمی"]
        if "asset_class" in df.columns:
            df = df[df["asset_class"].isin(allowed_assets)]

        price_col = df["close_price"].where(df["close_price"] > 0, df["last_price"])

        # Calculate values
        df["trade_val_b_toman"] = df["value"] / self.RIALS_TO_BILLION_TOMAN
        df["real_buy_val_rials"] = df["buy_vol_real"] * price_col
        df["real_sell_val_rials"] = df["sell_vol_real"] * price_col
        df["net_real_inflow_b_toman"] = (df["real_buy_val_rials"] - df["real_sell_val_rials"]) / self.RIALS_TO_BILLION_TOMAN

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
            0.0
        )

        df["volume_to_base_ratio"] = np.where(
            df["base_volume"] > 0,
            df["volume"] / df["base_volume"],
            1.0
        )

        # Apply basic liquidity and activity filters
        filtered = df[
            (df["trade_val_b_toman"] >= self.min_trade_value_b_toman) &
            (df["buyer_power_ratio"] >= self.min_buyer_power) &
            (df["buy_per_capita_m_toman"] >= self.min_buy_per_capita_m_toman) &
            (df["net_real_inflow_b_toman"] >= self.min_net_inflow_b_toman)
        ].copy()

        candidates: List[SmartMoneyCandidate] = []

        for _, row in filtered.iterrows():
            score, strength, rationale = self._calculate_smart_money_score(row, top_sectors)

            candidates.append(
                SmartMoneyCandidate(
                    symbol=str(row.get("symbol", "")),
                    name=str(row.get("name", "")),
                    sector_name=str(row.get("sector_name", "")),
                    close_price=float(row.get("close_price", 0.0)),
                    pct_change_close=float(row.get("pct_change_close", 0.0)),
                    pct_change_last=float(row.get("pct_change_last", 0.0)),
                    total_trade_value_b_toman=round(float(row.get("trade_val_b_toman", 0.0)), 2),
                    net_real_inflow_b_toman=round(float(row.get("net_real_inflow_b_toman", 0.0)), 2),
                    buy_per_capita_m_toman=round(float(row.get("buy_per_capita_m_toman", 0.0)), 1),
                    sell_per_capita_m_toman=round(float(row.get("sell_per_capita_m_toman", 0.0)), 1),
                    buyer_power_ratio=round(float(row.get("buyer_power_ratio", 0.0)), 2),
                    volume_to_base_ratio=round(float(row.get("volume_to_base_ratio", 0.0)), 2),
                    smart_money_score=round(score, 1),
                    signal_strength=strength,
                    rationale=rationale
                )
            )

        # Sort descending by Smart Money Score
        candidates.sort(key=lambda c: c.smart_money_score, reverse=True)
        return candidates

    def _calculate_smart_money_score(
        self,
        row: pd.Series,
        top_sectors: Optional[List[str]] = None
    ) -> (float, str, str):
        """
        Computes composite 0-100 score and rationale.
        """
        power = float(row.get("buyer_power_ratio", 1.0))
        buy_capita = float(row.get("buy_per_capita_m_toman", 0.0))
        net_inflow = float(row.get("net_real_inflow_b_toman", 0.0))
        vol_ratio = float(row.get("volume_to_base_ratio", 1.0))
        sector = str(row.get("sector_name", ""))
        pct_change = float(row.get("pct_change_close", 0.0))

        # 1. Buyer Power Component (Max 35 pts)
        # Power >= 3.0 -> 35 pts, Power 1.5 -> ~17.5 pts
        power_score = min(35.0, (power / 3.0) * 35.0)

        # 2. Per Capita Buy Component (Max 25 pts)
        # Capita >= 100M -> 25 pts, 40M -> 10 pts
        capita_score = min(25.0, (buy_capita / 100.0) * 25.0)

        # 3. Net Inflow & Liquidity Component (Max 20 pts)
        # Net inflow >= 10B Toman -> 20 pts
        inflow_score = min(20.0, (net_inflow / 10.0) * 20.0)

        # 4. Volume Anomaly Component (Max 10 pts)
        # Vol to base >= 3.0 -> 10 pts
        vol_score = min(10.0, (vol_ratio / 3.0) * 10.0)

        # 5. Sector Alignment Component (Max 10 pts)
        sector_score = 10.0 if top_sectors and sector in top_sectors else 5.0

        total_score = power_score + capita_score + inflow_score + vol_score + sector_score
        total_score = min(100.0, max(0.0, total_score))

        # Determine signal strength and description
        rationales = []
        if power >= 2.0:
            rationales.append(f"قدرت خریدار عالی ({power:.2f})")
        elif power >= 1.5:
            rationales.append(f"قدرت خریدار مناسب ({power:.2f})")

        if buy_capita >= 50.0:
            rationales.append(f"سرانه خرید سنگین ({buy_capita:.0f} م.ت)")

        if net_inflow >= 2.0:
            rationales.append(f"ورود خالص {net_inflow:+.1f} همت")

        if vol_ratio >= 2.0:
            rationales.append(f"حجم {vol_ratio:.1f} برابر مبنا")

        if top_sectors and sector in top_sectors:
            rationales.append(f"همگام با صنعت پیشتاز ({sector})")

        rationale_str = " | ".join(rationales) if rationales else "ورود پول هوشمند اولیه"

        if total_score >= 80.0:
            strength = "🔥 بسیار قوی (Very High)"
        elif total_score >= 65.0:
            strength = "✅ قوی (High)"
        elif total_score >= 50.0:
            strength = "⚠️ متوسط (Moderate)"
        else:
            strength = "ضعیف (Low)"

        return total_score, strength, rationale_str
