"""
1-3 Day Swing Signal Generator & Risk Management Engine for Iranian Market.
Integrates Macro gates, Sector momentum, and Stock-level smart money accumulation.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np

from src.analytics.macro_flow import MacroFlowReport
from src.analytics.sector_rotation import SectorFlowSummary
from src.analytics.smart_money_screener import SmartMoneyCandidate


@dataclass
class TradingSignal:
    symbol: str
    name: str
    sector_name: str
    entry_price: float
    target_price_tp: float
    stop_loss_price_sl: float
    expected_gain_pct: float
    expected_loss_pct: float
    risk_reward_ratio: float
    holding_days_max: int
    smart_money_score: float
    suggested_weight_pct: float
    action: str
    rationale: str


@dataclass
class DailyActionPlan:
    macro_status: str
    capital_allocation_summary: str
    equity_allocation_pct: float
    fixed_income_allocation_pct: float
    buy_signals: List[TradingSignal]
    risk_warnings: List[str]


class SignalGenerator:
    """
    Generates structured 1-3 day swing trading signals.
    """

    def generate(
        self,
        macro_report: MacroFlowReport,
        sector_summaries: List[SectorFlowSummary],
        candidates: List[SmartMoneyCandidate],
        max_positions: int = 5,
        min_signal_score: float = 60.0
    ) -> DailyActionPlan:
        """
        Synthesizes macro, sector, and ticker inputs into an actionable daily trade plan.
        """
        top_inflow_sectors = [
            s.sector_name for s in sector_summaries if s.net_real_inflow_b_toman > 0
        ][:5]

        warnings = []
        signals: List[TradingSignal] = []

        # 1. Macro Risk Assessment
        if "Defensive" in macro_report.market_sentiment or "خروج" in macro_report.smart_money_verdict:
            warnings.append("⚠️ ریسک کلان بالا: جریان نقدینگی در حال خروج از بازار سهام است.")
            equity_pct = 20.0
            fi_pct = 80.0
        elif "Hedge" in macro_report.market_sentiment:
            warnings.append("⚠️ احتیاط: نقدینگی اصلی به سمت صندوق‌های طلا هدایت شده است.")
            equity_pct = 30.0
            fi_pct = 70.0
        elif "Bullish" in macro_report.market_sentiment:
            equity_pct = 85.0
            fi_pct = 15.0
        else:
            equity_pct = 50.0
            fi_pct = 50.0

        # 2. Filter Candidate Tickers
        valid_candidates = [
            c for c in candidates if c.smart_money_score >= min_signal_score
        ]

        if not valid_candidates:
            allocation_summary = (
                f"🛡️ تخصیص کامل به صندوق‌های درآمد ثابت ({fi_pct:.0f}%) — سیگنال ورود هوشمند معتبری در سهام کشف نشد."
            )
            return DailyActionPlan(
                macro_status=macro_report.market_sentiment,
                capital_allocation_summary=allocation_summary,
                equity_allocation_pct=0.0,
                fixed_income_allocation_pct=100.0,
                buy_signals=[],
                risk_warnings=warnings
            )

        # Select top candidates up to max_positions
        selected = valid_candidates[:max_positions]
        position_weight = round(equity_pct / len(selected), 1) if selected else 0.0

        for c in selected:
            entry = c.close_price if c.close_price > 0 else 1.0

            # Dynamic Triple Barrier Targets (1-3 days):
            # Target Profit: +5.5% to +8.5% (2 to 3 days of positive limit moves)
            # Stop Loss: -3.0%
            tp_pct = 6.5 if c.smart_money_score >= 75.0 else 5.0
            sl_pct = 3.0

            target_price = round(entry * (1.0 + tp_pct / 100.0), 0)
            stop_loss = round(entry * (1.0 - sl_pct / 100.0), 0)
            rr_ratio = round(tp_pct / sl_pct, 2)

            signals.append(
                TradingSignal(
                    symbol=c.symbol,
                    name=c.name,
                    sector_name=c.sector_name,
                    entry_price=entry,
                    target_price_tp=target_price,
                    stop_loss_price_sl=stop_loss,
                    expected_gain_pct=tp_pct,
                    expected_loss_pct=sl_pct,
                    risk_reward_ratio=rr_ratio,
                    holding_days_max=3,
                    smart_money_score=c.smart_money_score,
                    suggested_weight_pct=position_weight,
                    action="خرید نوسانی ۱ تا ۳ روزه (BUY)",
                    rationale=c.rationale
                )
            )

        allocation_summary = (
            f"📊 تخصیص سرمایه پیشنهادی: {equity_pct:.0f}% در سهام منتخب ({len(signals)} موقعیت) "
            f"و {fi_pct:.0f}% پارک در صندوق‌های درآمد ثابت (کاردان / افران / اعتماد)."
        )

        return DailyActionPlan(
            macro_status=macro_report.market_sentiment,
            capital_allocation_summary=allocation_summary,
            equity_allocation_pct=equity_pct,
            fixed_income_allocation_pct=fi_pct,
            buy_signals=signals,
            risk_warnings=warnings
        )
