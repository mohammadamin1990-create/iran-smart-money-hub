"""
Phase 3: Multi-Regime Dynamic Asset Allocation Engine (موتور تخصیص پویای دارایی بین ۴ طبقه)
Dynamically allocates capital across:
  1. صندوق‌های اهرمی (Leveraged ETFs)
  2. صندوق‌های طلا (Gold ETFs)
  3. صندوق‌های درآمد ثابت (Fixed-Income ETFs)
  4. سهام پیشرو با ورود پول هوشمند (High-Conviction Stocks)

Determines macro market regime by synthesizing:
  - Bourse Smart Money Flow (MacroFlowReport)
  - Currency & Dubai Dirham Parity Radar (FXMacroRadarSnapshot)
  - Sector Rotation Momentum (SectorFlowSummary)
"""

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional
import pandas as pd


class MarketRegime(Enum):
    BULL_EQUITY = "رونق و رالی صعودی سهام (Risk-On Bull Equity)"
    FX_CRISIS_GOLD = "جهش ارزی و پناه به طلا (FX Surge & Gold Rush)"
    BEAR_CRASH = "رکود و خروج سرمایه به درآمد ثابت (Risk-Off Bear Market)"
    RANGE_ROTATION = "بازار رنج و چرخش هوشمند بین صنایع (Range-Bound Sector Rotation)"


@dataclass
class AssetClassAllocation:
    asset_class: str
    target_weight_pct: float
    recommended_symbol: str
    recommended_name: str
    rationale: str


@dataclass
class DynamicAllocationPlan:
    regime: MarketRegime
    regime_rationale: str
    allocations: List[AssetClassAllocation]
    rebalance_urgency: str
    risk_level: str
    total_weight_pct: float = 100.0


class MultiRegimeAssetAllocator:
    """
    Computes optimal portfolio allocation across the 4 core Iranian asset classes.
    """

    def __init__(self):
        pass

    def determine_regime(
        self,
        equity_net_inflow_b_toman: float,
        buyer_power_ratio: float,
        dirham_spread_pct: float,
        gold_flow_b_toman: float = 0.0
    ) -> tuple[MarketRegime, str]:
        """
        Classifies current market condition into one of the 4 core regimes.
        """
        # Regime 1: Bull Equity (Strong inflows to equity, positive power)
        if equity_net_inflow_b_toman >= 150.0 and buyer_power_ratio >= 1.25:
            return (
                MarketRegime.BULL_EQUITY,
                f"ورود سنگین پول هوشمند به سهام (+{equity_net_inflow_b_toman:,.0f} میلیارد تومان) و سرانه خریدار قوی ({buyer_power_ratio:.2f})؛ "
                "رژیم غالب: رونق بورس. تمرکز بر اهرمی‌ها و سهام پیشرو."
            )

        # Regime 2: FX Crisis & Gold Flight (Dirham leading by > 0.8% or heavy gold rush)
        if dirham_spread_pct >= 0.8 or (gold_flow_b_toman >= 80.0 and equity_net_inflow_b_toman <= 0.0):
            return (
                MarketRegime.FX_CRISIS_GOLD,
                f"پیشتازی حواله درهم دبی (اسپرد {dirham_spread_pct:+.2f}٪) و ورود تقاضا به بازار طلا؛ "
                "رژیم غالب: جهش ارزی. حداکثر وزن به صندوق‌های طلا (با حباب پایین)."
            )

        # Regime 3: Bear Crash (Heavy equity outflows and weak buyer power)
        if equity_net_inflow_b_toman <= -150.0 and buyer_power_ratio < 0.9:
            return (
                MarketRegime.BEAR_CRASH,
                f"خروج گسترده نقدینگی از بازار سهام ({equity_net_inflow_b_toman:,.0f} میلیارد تومان) و غلبه فروشندگان خرد؛ "
                "رژیم غالب: خروج پول و رکود. پناه حداکثری به صندوق‌های درآمد ثابت دارای بافر سود."
            )

        # Regime 4: Range-Bound & Sector Rotation
        return (
            MarketRegime.RANGE_ROTATION,
            "تعادل کلی شاخص و نبود هیجان شدید ارزی؛ نقدینگی در حال چرخش انتخابی بین صنایع پیشرو است. "
            "رژیم غالب: بازار خنثی با فرصت‌های نوسان‌گیری تک‌سهم و پایش اهرمی‌های عقب‌افتاده."
        )

    def generate_plan(
        self,
        equity_net_inflow_b_toman: float,
        buyer_power_ratio: float,
        dirham_spread_pct: float,
        best_gold_symbol: str = "عیار",
        best_gold_name: str = "صندوق طلای عیار مفید",
        catch_up_leveraged_symbol: str = "شتاب",
        catch_up_leveraged_name: str = "صندوق شتاب مفید",
        best_fixed_income_symbol: str = "ارمغان",
        best_fixed_income_name: str = "صندوق درآمد ثابت ارمغان ایرانیان",
        top_stock_symbol: str = "فولاد",
        top_stock_name: str = "فولاد مبارکه اصفهان",
        gold_flow_b_toman: float = 0.0
    ) -> DynamicAllocationPlan:
        """
        Builds the 100% portfolio allocation breakdown for the active regime.
        """
        regime, rationale = self.determine_regime(
            equity_net_inflow_b_toman=equity_net_inflow_b_toman,
            buyer_power_ratio=buyer_power_ratio,
            dirham_spread_pct=dirham_spread_pct,
            gold_flow_b_toman=gold_flow_b_toman
        )

        allocations: List[AssetClassAllocation] = []

        if regime == MarketRegime.BULL_EQUITY:
            allocations = [
                AssetClassAllocation(
                    asset_class="صندوق‌های اهرمی (Leveraged ETF)",
                    target_weight_pct=40.0,
                    recommended_symbol=catch_up_leveraged_symbol,
                    recommended_name=catch_up_leveraged_name,
                    rationale="بهره‌گیری حداکثری از گام‌های صعودی شاخص کل با ضریب اهرمی بهینه و اسپرد تعدیل‌شده."
                ),
                AssetClassAllocation(
                    asset_class="سهام پیشرو و مستعد نوسان (High-Conviction Stocks)",
                    target_weight_pct=30.0,
                    recommended_symbol=top_stock_symbol,
                    recommended_name=top_stock_name,
                    rationale="تمرکز روی صنایع لیدر جریان نقدینگی هوشمند با نسبت ریسک به ریوارد بالا."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های طلا (Gold ETF)",
                    target_weight_pct=15.0,
                    recommended_symbol=best_gold_symbol,
                    recommended_name=best_gold_name,
                    rationale="پوشش ریسک و حفظ ارزش دلاری سبد سرمایه‌گذاری."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های درآمد ثابت (Fixed Income)",
                    target_weight_pct=15.0,
                    recommended_symbol=best_fixed_income_symbol,
                    recommended_name=best_fixed_income_name,
                    rationale="بافر نقدینگی و نقدشوندگی فوری برای شکار اصلاح‌های مقطعی بازار."
                ),
            ]
            urgency = "🟡 متوسط (بازچینی تدریجی به سمت دارایی‌های پرریسک)"
            risk = "بالا (تهاجمی / Pro-Growth)"

        elif regime == MarketRegime.FX_CRISIS_GOLD:
            allocations = [
                AssetClassAllocation(
                    asset_class="صندوق‌های طلا (Gold ETF)",
                    target_weight_pct=50.0,
                    recommended_symbol=best_gold_symbol,
                    recommended_name=best_gold_name,
                    rationale="بزرگترین لنگرگاه حفظ ارزش در فاز جهش نرخ ارز و پیشتازی درهم دبی با کمترین حباب."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های درآمد ثابت (Fixed Income)",
                    target_weight_pct=25.0,
                    recommended_symbol=best_fixed_income_symbol,
                    recommended_name=best_fixed_income_name,
                    rationale="دریافت سود تضمینی مرکب سالانه و امنیت سرمایه بدون ریسک نوسان بازار."
                ),
                AssetClassAllocation(
                    asset_class="سهام پیشرو صادرات‌محور (FX-Hedged Stocks)",
                    target_weight_pct=15.0,
                    recommended_symbol=top_stock_symbol,
                    recommended_name=top_stock_name,
                    rationale="سهام با درآمد دلاری و منتفع از رشد نرخ نیما و ارز آزاد."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های اهرمی (Leveraged ETF)",
                    target_weight_pct=10.0,
                    recommended_symbol=catch_up_leveraged_symbol,
                    recommended_name=catch_up_leveraged_name,
                    rationale="حداقل پوزیشن اهرمی برای عدم جا ماندن از سوار شدن سهام بر تورم ارزی."
                ),
            ]
            urgency = "🔴 فوری (انتقال وزن اصلی به طلا جهت پوشش کاهش ارزش ریال)"
            risk = "متوسط به بالا (ارزی و پدافندی)"

        elif regime == MarketRegime.BEAR_CRASH:
            allocations = [
                AssetClassAllocation(
                    asset_class="صندوق‌های درآمد ثابت (Fixed Income)",
                    target_weight_pct=60.0,
                    recommended_symbol=best_fixed_income_symbol,
                    recommended_name=best_fixed_income_name,
                    rationale="حفظ ۱۰۰٪ اصل سرمایه در فاز رکود با انتخاب صندوق‌های دارای بالاترین بافر ذخیره ارزش."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های طلا (Gold ETF)",
                    target_weight_pct=30.0,
                    recommended_symbol=best_gold_symbol,
                    recommended_name=best_gold_name,
                    rationale="دارایی امن و پناهگاه سرمایه در شرایط تنش و بی اعتمادی به بورس."
                ),
                AssetClassAllocation(
                    asset_class="سهام پیشرو و نقدینگی (Equity)",
                    target_weight_pct=10.0,
                    recommended_symbol=top_stock_symbol,
                    recommended_name=top_stock_name,
                    rationale="نقدینگی در گردش برای خریدهای پله‌ای در کف‌های حمایتی بسیار معتبر."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های اهرمی (Leveraged ETF)",
                    target_weight_pct=0.0,
                    recommended_symbol="—",
                    recommended_name="خروج کامل",
                    rationale="⛔ ممنوعیت قطعی ورود به صندوق‌های اهرمی به دلیل تشدید مضاعف زیان در فاز نزولی."
                ),
            ]
            urgency = "🔴 فوری (خروج بی‌درنگ از اهرمی‌ها و انتقال به درآمد ثابت)"
            risk = "بسیار پایین (تدافعی و محافظتی)"

        else:  # RANGE_ROTATION
            allocations = [
                AssetClassAllocation(
                    asset_class="سهام پیشرو صنایع لیدر (Top Sector Stocks)",
                    target_weight_pct=35.0,
                    recommended_symbol=top_stock_symbol,
                    recommended_name=top_stock_name,
                    rationale="تمرکز روی صنایع لیدر چرخش پول هوشمند در بازه‌های زمانی ۱ تا ۳ روزه."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های درآمد ثابت (Fixed Income)",
                    target_weight_pct=30.0,
                    recommended_symbol=best_fixed_income_symbol,
                    recommended_name=best_fixed_income_name,
                    rationale="ستون فقرات ثبات سبد و تأمین نقدینگی سریع برای چرخش بین صنایع."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های طلا (Gold ETF)",
                    target_weight_pct=20.0,
                    recommended_symbol=best_gold_symbol,
                    recommended_name=best_gold_name,
                    rationale="حفاظت سبد در برابر نوسانات ناگهانی ارز و اخبار ژئوپلیتیک."
                ),
                AssetClassAllocation(
                    asset_class="صندوق‌های اهرمی (Leveraged ETF)",
                    target_weight_pct=15.0,
                    recommended_symbol=catch_up_leveraged_symbol,
                    recommended_name=catch_up_leveraged_name,
                    rationale="نوسان‌گیری کوتاه‌مدت صرفاً روی صندوق‌های دارای اهرم واقعی بالا و حباب منفی."
                ),
            ]
            urgency = "🟢 عادی (پایش روزانه چرخش نقدینگی بین صنایع)"
            risk = "متعادل (Balanced Allocation)"

        return DynamicAllocationPlan(
            regime=regime,
            regime_rationale=rationale,
            allocations=allocations,
            rebalance_urgency=urgency,
            risk_level=risk
        )


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    allocator = MultiRegimeAssetAllocator()

    print("=== تست ۴ رژیم تخصیص دارایی ===")
    for test_name, (eq_inflow, power, spread, g_flow) in [
        ("رژیم ۱: صعود بورس", (350.0, 1.45, 0.2, 10.0)),
        ("رژیم ۲: جهش درهم و ارز", (-20.0, 0.95, 1.35, 120.0)),
        ("رژیم ۳: ریزش و رکود بازار", (-250.0, 0.72, -0.4, -10.0)),
        ("رژیم ۴: بازار رنج و متعادل", (40.0, 1.08, 0.35, 15.0)),
    ]:
        plan = allocator.generate_plan(
            equity_net_inflow_b_toman=eq_inflow,
            buyer_power_ratio=power,
            dirham_spread_pct=spread,
            gold_flow_b_toman=g_flow
        )
        print(f"\n--- {test_name} ---")
        print(f"رژیم: {plan.regime.value}")
        print(f"منطق: {plan.regime_rationale}")
        print(f"فوریت بازچینی: {plan.rebalance_urgency} | سطح ریسک: {plan.risk_level}")
        for a in plan.allocations:
            print(f"  • {a.asset_class:35s} | وزن: {a.target_weight_pct:4.1f}% | نماد: {a.recommended_symbol:8s} | {a.rationale[:55]}...")
