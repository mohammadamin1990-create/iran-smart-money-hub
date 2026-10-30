"""
Sector Rotation & Industry Money Flow Analyzer for Iranian Capital Market.
Identifies which sectors are accumulating smart money vs. which are experiencing liquidity drain.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd
import numpy as np


@dataclass
class SectorFlowSummary:
    sector_code: str
    sector_name: str
    total_trade_value_b_toman: float
    net_real_inflow_b_toman: float
    inflow_intensity_pct: float
    avg_buyer_power: float
    avg_price_change: float
    top_inflow_tickers: List[str]
    tickers_count: int


class SectorRotationAnalyzer:
    """
    Computes sector-level smart money metrics and rankings.
    """

    RIALS_TO_BILLION_TOMAN = 1e10
    RIALS_TO_MILLION_TOMAN = 1e7

    def analyze(self, df: pd.DataFrame, min_sector_value_b_toman: float = 1.0) -> List[SectorFlowSummary]:
        """
        Analyzes stock data grouped by sector.
        Only considers equities (excludes ETFs / fixed income to avoid skewing industry metrics).
        """
        if df.empty:
            return []

        # Filter out pure funds so sector metrics reflect actual operating industries
        stocks_df = df[df.get("asset_class", "سهام و حق تقدم") == "سهام و حق تقدم"].copy()
        if stocks_df.empty:
            stocks_df = df.copy()

        price_col = stocks_df["close_price"].where(stocks_df["close_price"] > 0, stocks_df["last_price"])

        stocks_df["real_buy_val_rials"] = stocks_df["buy_vol_real"] * price_col
        stocks_df["real_sell_val_rials"] = stocks_df["sell_vol_real"] * price_col
        stocks_df["net_real_inflow_rials"] = stocks_df["real_buy_val_rials"] - stocks_df["real_sell_val_rials"]

        stocks_df["buy_per_capita_m_toman"] = np.where(
            stocks_df["buy_count_real"] > 0,
            (stocks_df["real_buy_val_rials"] / stocks_df["buy_count_real"]) / self.RIALS_TO_MILLION_TOMAN,
            0.0
        )
        stocks_df["sell_per_capita_m_toman"] = np.where(
            stocks_df["sell_count_real"] > 0,
            (stocks_df["real_sell_val_rials"] / stocks_df["sell_count_real"]) / self.RIALS_TO_MILLION_TOMAN,
            0.0
        )
        stocks_df["buyer_power_ratio"] = np.where(
            stocks_df["sell_per_capita_m_toman"] > 0,
            stocks_df["buy_per_capita_m_toman"] / stocks_df["sell_per_capita_m_toman"],
            1.0
        )

        sector_summaries: List[SectorFlowSummary] = []

        for (sector_code, sector_name), group in stocks_df.groupby(["sector_code", "sector_name"]):
            tot_val = group["value"].sum() / self.RIALS_TO_BILLION_TOMAN
            if tot_val < min_sector_value_b_toman:
                continue

            net_inflow = group["net_real_inflow_rials"].sum() / self.RIALS_TO_BILLION_TOMAN
            inflow_intensity = (net_inflow / tot_val * 100.0) if tot_val > 0 else 0.0

            valid_power = group[group["sell_per_capita_m_toman"] > 0]
            avg_power = (
                (valid_power["buyer_power_ratio"] * valid_power["value"]).sum() / valid_power["value"].sum()
                if not valid_power.empty and valid_power["value"].sum() > 0
                else 1.0
            )

            avg_price_change = (
                (group["pct_change_close"] * group["value"]).sum() / group["value"].sum()
                if group["value"].sum() > 0
                else group["pct_change_close"].mean()
            )

            # Find top inflow tickers within this sector
            top_tickers = (
                group.sort_values(by="net_real_inflow_rials", ascending=False)
                .head(3)["symbol"]
                .tolist()
            )

            sector_summaries.append(
                SectorFlowSummary(
                    sector_code=str(sector_code),
                    sector_name=str(sector_name),
                    total_trade_value_b_toman=round(tot_val, 1),
                    net_real_inflow_b_toman=round(net_inflow, 1),
                    inflow_intensity_pct=round(inflow_intensity, 1),
                    avg_buyer_power=round(avg_power, 2),
                    avg_price_change=round(avg_price_change, 2),
                    top_inflow_tickers=top_tickers,
                    tickers_count=len(group)
                )
            )

        # Sort sectors by Net Real Inflow descending
        sector_summaries.sort(key=lambda s: s.net_real_inflow_b_toman, reverse=True)
        return sector_summaries
