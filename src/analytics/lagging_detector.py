"""
Unified Lagging & Valuation Detector for Iranian ETFs.
Combines Synthetic Gold NAV and Dynamic Leveraged Return Spreads.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import pandas as pd

from src.analytics.gold_synthetic_nav import GoldSyntheticNAVEngine, GoldFundValuation
from src.analytics.leveraged_analytics import LeveragedFundAnalyzer, LeveragedFundAnalysis


@dataclass
class ValuationLaggingReport:
    gold_valuations: List[GoldFundValuation]
    leveraged_analyses: List[LeveragedFundAnalysis]
    best_gold_fund: Optional[GoldFundValuation]
    overheated_gold_funds: List[GoldFundValuation]
    top_catch_up_leveraged: Optional[LeveragedFundAnalysis]
    leveraged_leader: Optional[LeveragedFundAnalysis]
    key_takeaways: List[str]


class ValuationLaggingDetector:
    """
    Unified manager for Gold Synthetic NAV and Leveraged Catch-Up detection.
    """

    def __init__(self, min_trade_value_b_toman: float = 10.0):
        self.gold_engine = GoldSyntheticNAVEngine(min_trade_value_b_toman=min_trade_value_b_toman)
        self.leveraged_engine = LeveragedFundAnalyzer(min_trade_value_b_toman=min_trade_value_b_toman)

    def analyze(
        self,
        df: pd.DataFrame,
        spot_gold_change_pct: float = 0.0,
        live_leverage_map: Optional[Dict[str, any]] = None
    ) -> ValuationLaggingReport:
        """
        Runs complete valuation and lagging analysis across gold and leveraged funds.
        """
        gold_vals = self.gold_engine.calculate_valuations(df, spot_gold_change_pct=spot_gold_change_pct)
        best_gold = self.gold_engine.pick_best_gold_fund(gold_vals)
        overheated_gold = [g for g in gold_vals if g.synthetic_bubble_pct >= 10.0]

        lev_analyses = self.leveraged_engine.analyze(df, live_leverage_map=live_leverage_map)

        # Leader is the one with adjusted_spread == 0
        leader = next((l for l in lev_analyses if l.adjusted_spread_vs_leader == 0.0), None)
        # Top catch-up is the highest scoring non-leader liquid fund with positive spread
        catch_up_candidates = [
            l for l in lev_analyses
            if l.is_liquid and l.adjusted_spread_vs_leader >= 0.8 and (leader is None or l.symbol != leader.symbol)
        ]
        top_catch_up = catch_up_candidates[0] if catch_up_candidates else None

        takeaways = []

        # Gold Insights
        if best_gold:
            takeaways.append(
                f"🥇 بهترین صندوق طلا: «{best_gold.symbol}» با حباب زنده {best_gold.synthetic_bubble_pct:+.1f}% "
                f"و ارزش معاملات {best_gold.trade_value_b_toman:.1f} همت (کمترین ریسک حباب)."
            )
        if overheated_gold:
            symbols = ", ".join([g.symbol for g in overheated_gold])
            takeaways.append(
                f"⚠️ هشدار حباب داغ طلا: نمادهای ({symbols}) با حباب بالای ۱۰٪ معامله می‌شوند؛ ریسک تخلیه حباب بالاست."
            )

        # Leveraged Insights
        if leader and leader.is_queue_locked:
            takeaways.append(
                f"🚀 لیدر اهرمی قفل در صف خرید: «{leader.symbol}» به سقف قیمت رسیده است."
            )
            if top_catch_up:
                takeaways.append(
                    f"🎯 فرصت جهش عقب‌افتاده: «{top_catch_up.symbol}» با ضریب اهرم {top_catch_up.leverage_ratio}x "
                    f"هنوز فاصله تعدیل‌شده {top_catch_up.adjusted_spread_vs_leader:+.1f}% با لیدر دارد و مستعد پرواز است."
                )
        elif leader:
            takeaways.append(
                f"⚡ لیدر فعلی صندوق‌های اهرمی: «{leader.symbol}» با بازدهی تعدیل‌شده {leader.leverage_adjusted_return:+.1f}%."
            )

        return ValuationLaggingReport(
            gold_valuations=gold_vals,
            leveraged_analyses=lev_analyses,
            best_gold_fund=best_gold,
            overheated_gold_funds=overheated_gold,
            top_catch_up_leveraged=top_catch_up,
            leveraged_leader=leader,
            key_takeaways=takeaways
        )
