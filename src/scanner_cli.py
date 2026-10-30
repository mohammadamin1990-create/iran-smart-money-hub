"""
Command-Line Interface & Daily Scanner Runner for Iranian Market Smart Money Engine.
Displays beautiful terminal tables with Macro Flow, Sector Rotation, and Top 1-3 Day Signals.
"""

import argparse
import sys
import os
import io

# Ensure UTF-8 output encoding on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import pandas as pd
import numpy as np
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.text import Text

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.tsetmc_client import TSETMCClient
from src.data.fund_tracker import FundTracker
from src.analytics.macro_flow import MacroFlowAnalyzer, MacroFlowReport
from src.analytics.sector_rotation import SectorRotationAnalyzer, SectorFlowSummary
from src.analytics.smart_money_screener import SmartMoneyScreener, SmartMoneyCandidate
from src.analytics.lagging_detector import ValuationLaggingDetector, ValuationLaggingReport
from src.analytics.fx_macro_radar import FXMacroRadar, FXMacroRadarSnapshot
from src.analytics.asset_allocator import MultiRegimeAssetAllocator, DynamicAllocationPlan, MarketRegime
from src.signals.signal_generator import SignalGenerator, DailyActionPlan


console = Console(force_terminal=True, legacy_windows=False)



def create_demo_dataset() -> pd.DataFrame:
    """
    Generates a realistic Iranian market snapshot for testing and offline analysis.
    """
    data = [
        # Spot Gold Bullion Deposit Certificate (گواهی سپرده شمش طلا)
        {"inscode": "9999", "symbol": "طلاس", "name": "گواهی سپرده شمش طلا", "sector_code": "68", "close_price": 5200000, "last_price": 5304000, "yesterday_price": 5150000, "pct_change_close": 2.5, "pct_change_last": 3.0, "trades_count": 12000, "volume": 1_000_000, "value": 5_200_000_000_000, "base_volume": 1, "buy_count_real": 2000, "buy_count_legal": 10, "sell_count_real": 1500, "sell_count_legal": 5, "buy_vol_real": 800_000, "buy_vol_legal": 200_000, "sell_vol_real": 700_000, "sell_vol_legal": 300_000},

        # Leveraged Funds (اهرمی)
        # Leader: اهرم (Queue locked at ceiling +5.0%)
        {"inscode": "1001", "symbol": "اهرم", "name": "صندوق اهرم کاریزما", "sector_code": "68", "close_price": 24800, "last_price": 25000, "yesterday_price": 23810, "max_allowed_price": 25000, "nav": 23900, "pct_change_close": 4.1, "pct_change_last": 5.0, "trades_count": 8500, "volume": 120_000_000, "value": 2_940_000_000_000, "base_volume": 1, "buy_count_real": 2200, "buy_count_legal": 15, "sell_count_real": 5100, "sell_count_legal": 2, "buy_vol_real": 95_000_000, "buy_vol_legal": 25_000_000, "sell_vol_real": 60_000_000, "sell_vol_legal": 60_000_000},
        # Catch-Up Candidate: شتاب (Moving only +2.1% with 1.9x leverage -> High Adjusted Spread)
        {"inscode": "1003", "symbol": "شتاب", "name": "صندوق شتاب مفید", "sector_code": "68", "close_price": 18200, "last_price": 18400, "yesterday_price": 18020, "max_allowed_price": 18920, "nav": 18100, "pct_change_close": 1.0, "pct_change_last": 2.1, "trades_count": 5600, "volume": 80_000_000, "value": 1_456_000_000_000, "base_volume": 1, "buy_count_real": 1500, "buy_count_legal": 10, "sell_count_real": 1200, "sell_count_legal": 2, "buy_vol_real": 65_000_000, "buy_vol_legal": 15_000_000, "sell_vol_real": 40_000_000, "sell_vol_legal": 40_000_000},
        {"inscode": "1002", "symbol": "جهش", "name": "صندوق جهش فارابی", "sector_code": "68", "close_price": 18200, "last_price": 18500, "yesterday_price": 17800, "max_allowed_price": 18690, "nav": 17700, "pct_change_close": 3.2, "pct_change_last": 3.9, "trades_count": 4200, "volume": 45_000_000, "value": 819_000_000_000, "base_volume": 1, "buy_count_real": 1100, "buy_count_legal": 8, "sell_count_real": 2400, "sell_count_legal": 1, "buy_vol_real": 38_000_000, "buy_vol_legal": 7_000_000, "sell_vol_real": 22_000_000, "sell_vol_legal": 23_000_000},
        {"inscode": "1004", "symbol": "موج", "name": "صندوق موج فیروزه", "sector_code": "68", "close_price": 21000, "last_price": 21300, "yesterday_price": 20700, "max_allowed_price": 21735, "nav": 20500, "pct_change_close": 2.2, "pct_change_last": 2.9, "trades_count": 3100, "volume": 35_000_000, "value": 735_000_000_000, "base_volume": 1, "buy_count_real": 900, "buy_count_legal": 5, "sell_count_real": 1100, "sell_count_legal": 1, "buy_vol_real": 28_000_000, "buy_vol_legal": 7_000_000, "sell_vol_real": 18_000_000, "sell_vol_legal": 17_000_000},
        # Illiquid leveraged fund (< 10B Toman = 100 Billion Rials)
        {"inscode": "1005", "symbol": "نارنج", "name": "صندوق نارنج سهم", "sector_code": "68", "close_price": 10200, "last_price": 10200, "yesterday_price": 10100, "max_allowed_price": 10605, "nav": 10000, "pct_change_close": 1.0, "pct_change_last": 1.0, "trades_count": 150, "volume": 500_000, "value": 5_100_000_000, "base_volume": 1, "buy_count_real": 25, "buy_count_legal": 1, "sell_count_real": 30, "sell_vol_real": 400_000, "sell_vol_legal": 100_000, "buy_vol_real": 450_000, "buy_vol_legal": 50_000},

        # Gold Funds (صندوق‌های طلا)
        # Liquid, Undervalued synthetic bubble
        {"inscode": "2001", "symbol": "عیار", "name": "صندوق طلای عیار مفید", "sector_code": "68", "close_price": 142000, "last_price": 142500, "yesterday_price": 140000, "nav": 139500, "pct_change_close": 1.4, "pct_change_last": 1.8, "trades_count": 6200, "volume": 15_000_000, "value": 2_130_000_000_000, "base_volume": 1, "buy_count_real": 1800, "buy_count_legal": 5, "sell_count_real": 1600, "sell_count_legal": 2, "buy_vol_real": 9_000_000, "buy_vol_legal": 6_000_000, "sell_vol_real": 7_500_000, "sell_vol_legal": 7_500_000},
        # Liquid, Overheated bubble
        {"inscode": "2002", "symbol": "طلا", "name": "صندوق طلای لوتوس", "sector_code": "68", "close_price": 285000, "last_price": 298000, "yesterday_price": 280000, "nav": 265000, "pct_change_close": 4.5, "pct_change_last": 6.4, "trades_count": 4800, "volume": 8_000_000, "value": 2_280_000_000_000, "base_volume": 1, "buy_count_real": 1200, "buy_count_legal": 4, "sell_count_real": 1100, "sell_count_legal": 1, "buy_vol_real": 3_500_000, "buy_vol_legal": 4_500_000, "sell_vol_real": 4_800_000, "sell_vol_legal": 3_200_000},
        {"inscode": "2003", "symbol": "کهربا", "name": "صندوق طلای کهربا", "sector_code": "68", "close_price": 85000, "last_price": 85800, "yesterday_price": 84000, "nav": 83500, "pct_change_close": 1.2, "pct_change_last": 2.1, "trades_count": 3400, "volume": 12_000_000, "value": 1_020_000_000_000, "base_volume": 1, "buy_count_real": 950, "buy_count_legal": 3, "sell_count_real": 820, "sell_count_legal": 1, "buy_vol_real": 7_000_000, "buy_vol_legal": 5_000_000, "sell_vol_real": 6_000_000, "sell_vol_legal": 6_000_000},
        # Illiquid gold fund (< 10B Toman)
        {"inscode": "2004", "symbol": "زرفام", "name": "صندوق طلای زرفام", "sector_code": "68", "close_price": 45000, "last_price": 45000, "yesterday_price": 45500, "nav": 46000, "pct_change_close": -1.1, "pct_change_last": -1.1, "trades_count": 90, "volume": 100_000, "value": 4_500_000_000, "base_volume": 1, "buy_count_real": 15, "buy_count_legal": 1, "sell_count_real": 20, "sell_count_legal": 1, "buy_vol_real": 40_000, "buy_vol_legal": 60_000, "sell_vol_real": 50_000, "sell_vol_legal": 50_000},

        # Fixed Income Funds (Experiencing outflows)
        {"inscode": "3001", "symbol": "افران", "name": "صندوق درآمد ثابت افران", "sector_code": "68", "close_price": 10500, "last_price": 10500, "yesterday_price": 10495, "nav": 10500, "pct_change_close": 0.05, "pct_change_last": 0.05, "trades_count": 3500, "volume": 350_000_000, "value": 3_675_000_000_000, "base_volume": 1, "buy_count_real": 800, "buy_count_legal": 20, "sell_count_real": 2200, "sell_count_legal": 5, "buy_vol_real": 80_000_000, "buy_vol_legal": 270_000_000, "sell_vol_real": 220_000_000, "sell_vol_legal": 130_000_000},
        {"inscode": "3002", "symbol": "اعتماد", "name": "صندوق درآمد ثابت اعتماد", "sector_code": "68", "close_price": 10000, "last_price": 10000, "yesterday_price": 9995, "nav": 10000, "pct_change_close": 0.05, "pct_change_last": 0.05, "trades_count": 2100, "volume": 200_000_000, "value": 2_000_000_000_000, "base_volume": 1, "buy_count_real": 400, "buy_count_legal": 10, "sell_count_real": 1200, "sell_count_legal": 2, "buy_vol_real": 40_000_000, "buy_vol_legal": 160_000_000, "sell_vol_real": 110_000_000, "sell_vol_legal": 90_000_000},

        # Basic Metals (Top Inflow Sector)
        {"inscode": "4001", "symbol": "فولاد", "name": "فولاد مبارکه اصفهان", "sector_code": "27", "close_price": 5400, "last_price": 5580, "yesterday_price": 5217, "max_allowed_price": 5600, "nav": 0, "pct_change_close": 3.5, "pct_change_last": 4.8, "trades_count": 9200, "volume": 180_000_000, "value": 972_000_000_000, "base_volume": 20_000_000, "buy_count_real": 1800, "buy_count_legal": 12, "sell_count_real": 4200, "sell_count_legal": 3, "buy_vol_real": 145_000_000, "buy_vol_legal": 35_000_000, "sell_vol_real": 85_000_000, "sell_vol_legal": 95_000_000},
        {"inscode": "4002", "symbol": "فملی", "name": "ملی صنایع مس ایران", "sector_code": "27", "close_price": 7200, "last_price": 7450, "yesterday_price": 6977, "max_allowed_price": 7500, "nav": 0, "pct_change_close": 3.2, "pct_change_last": 4.6, "trades_count": 7800, "volume": 110_000_000, "value": 792_000_000_000, "base_volume": 15_000_000, "buy_count_real": 1400, "buy_count_legal": 10, "sell_count_real": 3100, "sell_count_legal": 2, "buy_vol_real": 90_000_000, "buy_vol_legal": 20_000_000, "sell_vol_real": 50_000_000, "sell_vol_legal": 60_000_000},
        {"inscode": "4003", "symbol": "ذوب", "name": "سهامی ذوب آهن اصفهان", "sector_code": "27", "close_price": 3100, "last_price": 3250, "yesterday_price": 2978, "max_allowed_price": 3300, "nav": 0, "pct_change_close": 4.1, "pct_change_last": 5.0, "trades_count": 6500, "volume": 140_000_000, "value": 434_000_000_000, "base_volume": 18_000_000, "buy_count_real": 900, "buy_count_legal": 5, "sell_count_real": 2800, "sell_count_legal": 1, "buy_vol_real": 120_000_000, "buy_vol_legal": 20_000_000, "sell_vol_real": 65_000_000, "sell_vol_legal": 75_000_000},

        # Chemicals & Petrochemicals
        {"inscode": "5001", "symbol": "نوری", "name": "پتروشیمی نوری", "sector_code": "44", "close_price": 285000, "last_price": 294000, "yesterday_price": 274300, "max_allowed_price": 295000, "nav": 0, "pct_change_close": 3.9, "pct_change_last": 5.0, "trades_count": 5100, "volume": 4_200_000, "value": 1_197_000_000_000, "base_volume": 800_000, "buy_count_real": 650, "buy_count_legal": 8, "sell_count_real": 1950, "sell_count_legal": 1, "buy_vol_real": 3_600_000, "buy_vol_legal": 600_000, "sell_vol_real": 1_500_000, "sell_vol_legal": 2_700_000},
        {"inscode": "5002", "symbol": "بوعلی", "name": "پتروشیمی بوعلی سینا", "sector_code": "44", "close_price": 94000, "last_price": 96500, "yesterday_price": 91440, "max_allowed_price": 98000, "nav": 0, "pct_change_close": 2.8, "pct_change_last": 4.2, "trades_count": 3800, "volume": 8_500_000, "value": 799_000_000_000, "base_volume": 1_200_000, "buy_count_real": 720, "buy_count_legal": 6, "sell_count_real": 1600, "sell_count_legal": 1, "buy_vol_real": 6_800_000, "buy_vol_legal": 1_700_000, "sell_vol_real": 3_500_000, "sell_vol_legal": 5_000_000},

        # Automotive (Losing money)
        {"inscode": "6001", "symbol": "خودرو", "name": "ایران خودرو", "sector_code": "34", "close_price": 2650, "last_price": 2600, "yesterday_price": 2682, "max_allowed_price": 2850, "nav": 0, "pct_change_close": -1.2, "pct_change_last": -1.9, "trades_count": 11000, "volume": 250_000_000, "value": 662_500_000_000, "base_volume": 25_000_000, "buy_count_real": 4200, "buy_count_legal": 4, "sell_count_real": 3100, "sell_count_legal": 10, "buy_vol_real": 90_000_000, "buy_vol_legal": 160_000_000, "sell_vol_real": 180_000_000, "sell_vol_legal": 70_000_000},
        {"inscode": "6002", "symbol": "خساپا", "name": "سایپا", "sector_code": "34", "close_price": 2320, "last_price": 2280, "yesterday_price": 2355, "max_allowed_price": 2500, "nav": 0, "pct_change_close": -1.5, "pct_change_last": -2.1, "trades_count": 8900, "volume": 210_000_000, "value": 487_200_000_000, "base_volume": 22_000_000, "buy_count_real": 3600, "buy_count_legal": 2, "sell_count_real": 2700, "sell_count_legal": 8, "buy_vol_real": 75_000_000, "buy_vol_legal": 135_000_000, "sell_vol_real": 150_000_000, "sell_vol_legal": 60_000_000},
    ]

    from src.data.tsetmc_client import SECTOR_MAP
    df = pd.DataFrame(data)
    df["sector_name"] = df["sector_code"].map(SECTOR_MAP).fillna("سایر")
    return df


def display_dashboard(
    macro_report: MacroFlowReport,
    sector_summaries: List[SectorFlowSummary],
    candidates: List[SmartMoneyCandidate],
    action_plan: DailyActionPlan
):
    """
    Renders the rich interactive dashboard.
    """
    console.print("\n")
    console.print(
        Panel.fit(
            "[bold cyan]🔍 سامانه هوشمند ردیابی گردش نقدینگی و پول هوشمند بورس تهران[/bold cyan]\n"
            "[italic white]Iranian Stock Market Smart Money & Capital Rotation Engine (1-3 Day Swing)[/italic white]",
            border_style="cyan"
        )
    )

    # 1. MACRO CAPITAL MIGRATION PANEL
    console.print("\n[bold yellow]═══ ۱. تحلیل کلان: گردش نقدینگی و منبع و مقصد پول ═══[/bold yellow]")
    console.print(f"[bold white]وضعیت کلان بازار:[/bold white] [bold green]{macro_report.market_sentiment}[/bold green]")
    console.print(f"[bold white]منبع تأمین پول:[/bold white] [red]{macro_report.source_asset}[/red]")
    console.print(f"[bold white]مقصد فرود پول:[/bold white] [green]{macro_report.destination_asset}[/green]")
    console.print(f"[bold white]تشخیص جریان پول هوشمند:[/bold white] {macro_report.smart_money_verdict}\n")

    macro_table = Table(title="📊 تراز ورود و خروج پول حقیقی بین دسته‌های دارایی", header_style="bold magenta")
    macro_table.add_column("دسته دارایی", justify="right", style="cyan")
    macro_table.add_column("ارزش معاملات (میلیارد تومان)", justify="center")
    macro_table.add_column("خرید حقیقی (م.ت)", justify="center")
    macro_table.add_column("فروش حقیقی (م.ت)", justify="center")
    macro_table.add_column("خالص ورود پول (م.ت)", justify="center")
    macro_table.add_column("قدرت خریدار", justify="center")

    for name, s in macro_report.asset_summaries.items():
        inflow_color = "[green]" if s.net_real_inflow_b_toman > 0 else "[red]"
        macro_table.add_row(
            name,
            f"{s.total_trade_value_b_toman:,.1f}",
            f"{s.real_buy_value_b_toman:,.1f}",
            f"{s.real_sell_value_b_toman:,.1f}",
            f"{inflow_color}{s.net_real_inflow_b_toman:+,.1f}[/]",
            f"{s.avg_buyer_power:.2f}"
        )
    console.print(macro_table)

    # 2. SECTOR ROTATION RANKINGS
    console.print("\n[bold yellow]═══ ۲. چرخش نقدینگی بین صنایع (Sector Rotation) ═══[/bold yellow]")
    sector_table = Table(title="🏆 رتبه‌بندی صنایع از نظر ورود پول هوشمند", header_style="bold blue")
    sector_table.add_column("رتبه", justify="center", style="dim")
    sector_table.add_column("نام صنعت", justify="right", style="bold white")
    sector_table.add_column("ارزش معاملات (م.ت)", justify="center")
    sector_table.add_column("خالص ورود پول (م.ت)", justify="center")
    sector_table.add_column("شدت ورود (%)", justify="center")
    sector_table.add_column("قدرت خریدار صنعت", justify="center")
    sector_table.add_column("نمادهای پیشتاز صنعت", justify="right", style="cyan")

    for rank, s in enumerate(sector_summaries[:6], 1):
        inflow_color = "[green]" if s.net_real_inflow_b_toman > 0 else "[red]"
        sector_table.add_row(
            str(rank),
            s.sector_name,
            f"{s.total_trade_value_b_toman:,.1f}",
            f"{inflow_color}{s.net_real_inflow_b_toman:+,.1f}[/]",
            f"{inflow_color}{s.inflow_intensity_pct:+.1f}%[/]",
            f"{s.avg_buyer_power:.2f}",
            ", ".join(s.top_inflow_tickers)
        )
    console.print(sector_table)

def display_dashboard(
    macro_report: MacroFlowReport,
    sector_summaries: List[SectorFlowSummary],
    val_report: ValuationLaggingReport,
    candidates: List[SmartMoneyCandidate],
    action_plan: DailyActionPlan,
    fx_snap: Optional[FXMacroRadarSnapshot] = None,
    allocation_plan: Optional[DynamicAllocationPlan] = None
):
    """
    Renders the rich interactive dashboard.
    """
    console.print("\n")
    console.print(
        Panel.fit(
            "[bold cyan]🔍 سامانه هوشمند ردیابی نقدینگی، ارزش‌گذاری و پورتفوی ETFهای بورس تهران (فاز ۱، ۲ و ۳)[/bold cyan]\n"
            "[italic white]Iranian Stock Market Smart Money, Synthetic NAV, FX Radar & Multi-Regime Asset Allocator[/italic white]",
            border_style="cyan"
        )
    )

    # 0. PHASE 2: FX MACRO & DIRHAM PARITY RADAR
    if fx_snap:
        fx_panel_text = (
            f"💵 [bold]دلار آزاد تهران:[/bold] {fx_snap.spot_usd_rials:,.0f} ریال   |   "
            f"🇦🇪 [bold]درهم حواله دبی:[/bold] {fx_snap.spot_aed_rials:,.0f} ریال   |   "
            f"📐 [bold]دلار محاسباتی از درهم:[/bold] {fx_snap.implied_usd_from_aed:,.0f} ریال\n"
            f"⚡ [bold]اسپرد آربیتراژ درهم:[/bold] [{ 'bold green' if fx_snap.dirham_arbitrage_spread_pct > 0.7 else 'bold red' if fx_snap.dirham_arbitrage_spread_pct < -0.7 else 'bold yellow'}]{fx_snap.dirham_arbitrage_spread_pct:+5.2f}%[/]   |   "
            f"🧭 [bold]رژیم کلان ارزی:[/bold] {fx_snap.macro_regime_signal}\n"
            f"💡 [dim]{fx_snap.macro_verdict}[/dim]"
        )
        console.print(Panel(fx_panel_text, title="🌍 رادار کلان ارزی و برابری درهم دبی (Phase 2 FX Radar)", border_style="blue"))

        if fx_snap.asset_dollar_bases:
            db_table = Table(title="💎 مقایسه دلار محاسباتی دارایی‌های طلامحور (Dollar-Base Bubbles)", header_style="bold magenta")
            db_table.add_column("دارایی / صندوق", justify="right", style="bold yellow")
            db_table.add_column("دلار محاسباتی (ریال)", justify="center", style="bold cyan")
            db_table.add_column("فاصله از دلار آزاد (%)", justify="center")
            db_table.add_column("وضعیت ارزندگی و آربیتراژ", justify="right")

            for a in fx_snap.asset_dollar_bases:
                color = "green" if a.premium_to_spot_pct < 0 else "yellow" if a.premium_to_spot_pct <= 5 else "red"
                db_table.add_row(
                    a.asset_name,
                    f"{a.implied_dollar_rials:,.0f}",
                    f"[{color}]{a.premium_to_spot_pct:+5.1f}%[/]",
                    a.status
                )
            console.print(db_table)
            console.print()

    # 1. MACRO CAPITAL MIGRATION PANEL
    console.print("\n[bold yellow]═══ ۱. تحلیل کلان: گردش نقدینگی و منبع و مقصد پول ═══[/bold yellow]")
    console.print(f"[bold white]وضعیت کلان بازار:[/bold white] [bold green]{macro_report.market_sentiment}[/bold green]")
    console.print(f"[bold white]منبع تأمین پول:[/bold white] [red]{macro_report.source_asset}[/red]")
    console.print(f"[bold white]مقصد فرود پول:[/bold white] [green]{macro_report.destination_asset}[/green]")
    console.print(f"[bold white]تشخیص جریان پول هوشمند:[/bold white] {macro_report.smart_money_verdict}\n")

    macro_table = Table(title="📊 تراز ورود و خروج پول حقیقی بین دسته‌های دارایی", header_style="bold magenta")
    macro_table.add_column("دسته دارایی", justify="right", style="cyan")
    macro_table.add_column("ارزش معاملات (میلیارد تومان)", justify="center")
    macro_table.add_column("خرید حقیقی (م.ت)", justify="center")
    macro_table.add_column("فروش حقیقی (م.ت)", justify="center")
    macro_table.add_column("خالص ورود پول (م.ت)", justify="center")
    macro_table.add_column("قدرت خریدار", justify="center")

    for name, s in macro_report.asset_summaries.items():
        inflow_color = "[green]" if s.net_real_inflow_b_toman > 0 else "[red]"
        macro_table.add_row(
            name,
            f"{s.total_trade_value_b_toman:,.1f}",
            f"{s.real_buy_value_b_toman:,.1f}",
            f"{s.real_sell_value_b_toman:,.1f}",
            f"{inflow_color}{s.net_real_inflow_b_toman:+,.1f}[/]",
            f"{s.avg_buyer_power:.2f}"
        )
    console.print(macro_table)

    # 2. SECTOR ROTATION RANKINGS
    console.print("\n[bold yellow]═══ ۲. چرخش نقدینگی بین صنایع (Sector Rotation) ═══[/bold yellow]")
    sector_table = Table(title="🏆 رتبه‌بندی صنایع از نظر ورود پول هوشمند", header_style="bold blue")
    sector_table.add_column("رتبه", justify="center", style="dim")
    sector_table.add_column("نام صنعت", justify="right", style="bold white")
    sector_table.add_column("ارزش معاملات (م.ت)", justify="center")
    sector_table.add_column("خالص ورود پول (م.ت)", justify="center")
    sector_table.add_column("شدت ورود (%)", justify="center")
    sector_table.add_column("قدرت خریدار صنعت", justify="center")
    sector_table.add_column("نمادهای پیشتاز صنعت", justify="right", style="cyan")

    for rank, s in enumerate(sector_summaries[:6], 1):
        inflow_color = "[green]" if s.net_real_inflow_b_toman > 0 else "[red]"
        sector_table.add_row(
            str(rank),
            s.sector_name,
            f"{s.total_trade_value_b_toman:,.1f}",
            f"{inflow_color}{s.net_real_inflow_b_toman:+,.1f}[/]",
            f"{inflow_color}{s.inflow_intensity_pct:+.1f}%[/]",
            f"{s.avg_buyer_power:.2f}",
            ", ".join(s.top_inflow_tickers)
        )
    console.print(sector_table)

    # 3. PHASE 1 REFINEMENTS: SYNTHETIC GOLD NAV & DYNAMIC LEVERAGED CATCH-UP
    console.print("\n[bold yellow]═══ ۳. موتور ارزش‌گذاری: حباب زنده (Synthetic NAV) و صندوق‌های عقب‌افتاده ═══[/bold yellow]")

    # 3.1 Gold Funds Table
    if val_report.gold_valuations:
        gold_table = Table(title="🪙 سنجش حباب زنده صندوق‌های طلا (Synthetic Live NAV)", header_style="bold yellow")
        gold_table.add_column("نماد", justify="right", style="bold yellow")
        gold_table.add_column("آخرین قیمت", justify="center")
        gold_table.add_column("NAV محاسباتی زنده", justify="center", style="cyan")
        gold_table.add_column("حباب زنده (%)", justify="center")
        gold_table.add_column("حباب رسمی (%)", justify="center", style="dim")
        gold_table.add_column("ارزش معاملات (م.ت)", justify="center")
        gold_table.add_column("ورود پول (م.ت)", justify="center")
        gold_table.add_column("وضعیت حباب و ارزندگی", justify="right")

        for g in val_report.gold_valuations:
            bubble_color = "[green]" if g.synthetic_bubble_pct <= 2.0 else ("[yellow]" if g.synthetic_bubble_pct <= 7.0 else "[red]")
            inflow_color = "[green]" if g.net_real_inflow_b_toman > 0 else "[red]"
            gold_table.add_row(
                g.symbol,
                f"{g.last_price:,.0f}",
                f"{g.synthetic_nav:,.0f}",
                f"{bubble_color}{g.synthetic_bubble_pct:+.1f}%[/]",
                f"{g.official_bubble_pct:+.1f}%",
                f"{g.trade_value_b_toman:,.1f}",
                f"{inflow_color}{g.net_real_inflow_b_toman:+,.1f}[/]",
                f"{g.valuation_status}"
            )
        console.print(gold_table)

    # 3.2 Leveraged Funds Table
    if val_report.leveraged_analyses:
        lev_table = Table(title="⚡ تحلیل صندوق‌های اهرمی، ضریب اهرم و کشف عقب‌افتاده‌ها (Catch-Up)", header_style="bold cyan")
        lev_table.add_column("نماد", justify="right", style="bold yellow")
        lev_table.add_column("قیمت", justify="center")
        lev_table.add_column("ضریب اهرم", justify="center", style="magenta")
        lev_table.add_column("بازدهی تابلو", justify="center")
        lev_table.add_column("بازدهی تعدیل‌شده", justify="center", style="bold cyan")
        lev_table.add_column("فاصله با لیدر (Spread)", justify="center")
        lev_table.add_column("حباب P/NAV", justify="center")
        lev_table.add_column("ارزش معاملات (م.ت)", justify="center")
        lev_table.add_column("توصیه الگوریتم عقب‌افتادگی", justify="right")

        for lev in val_report.leveraged_analyses:
            spread_color = "[green]" if lev.adjusted_spread_vs_leader >= 1.0 else "[white]"
            ret_color = "[green]" if lev.pct_change_last > 0 else "[red]"
            lev_table.add_row(
                lev.symbol,
                f"{lev.last_price:,.0f}",
                f"{lev.leverage_ratio:.2f}x",
                f"{ret_color}{lev.pct_change_last:+.1f}%[/]",
                f"{ret_color}{lev.leverage_adjusted_return:+.1f}%[/]",
                f"{spread_color}{lev.adjusted_spread_vs_leader:+.1f}%[/]",
                f"{lev.p_nav_bubble_pct:+.1f}%",
                f"{lev.trade_value_b_toman:,.1f}",
                lev.recommendation
            )
        console.print(lev_table)

    # Key Insights
    if val_report.key_takeaways:
        console.print("\n[bold cyan]💡 نکات کلیدی ارزش‌گذاری و آربیتراژ:[/bold cyan]")
        for insight in val_report.key_takeaways:
            console.print(f"  • {insight}")
        console.print("")

    # 4. ACTIONABLE 1-3 DAY SWING SIGNALS
    console.print("\n[bold yellow]═══ ۴. سیگنال‌های نوسان‌گیری ۱ تا ۳ روزه (Buy Position Signals) ═══[/bold yellow]")
    console.print(f"[bold cyan]{action_plan.capital_allocation_summary}[/bold cyan]\n")

    if action_plan.buy_signals:
        sig_table = Table(title="🎯 موقعیت‌های خرید تأیید شده با پول هوشمند (Triple Barrier Targets)", header_style="bold green")
        sig_table.add_column("نماد", justify="right", style="bold yellow")
        sig_table.add_column("نام شرکت", justify="right")
        sig_table.add_column("صنعت", justify="right", style="dim")
        sig_table.add_column("امتیاز هوشمند", justify="center", style="bold cyan")
        sig_table.add_column("قیمت ورود", justify="center")
        sig_table.add_column("حد سود TP (+%)", justify="center", style="green")
        sig_table.add_column("حد ضرر SL (-%)", justify="center", style="red")
        sig_table.add_column("نسبت R:R", justify="center")
        sig_table.add_column("وزن سبد", justify="center", style="bold magenta")
        sig_table.add_column("منطق سیگنال و ورود پول", justify="right")

        for sig in action_plan.buy_signals:
            sig_table.add_row(
                sig.symbol,
                sig.name,
                sig.sector_name,
                f"{sig.smart_money_score:.0f}/100",
                f"{sig.entry_price:,.0f}",
                f"{sig.target_price_tp:,.0f} (+{sig.expected_gain_pct}%)",
                f"{sig.stop_loss_price_sl:,.0f} (-{sig.expected_loss_pct}%)",
                f"{sig.risk_reward_ratio:.2f}",
                f"{sig.suggested_weight_pct:.0f}%",
                sig.rationale
            )
        console.print(sig_table)
    else:
        console.print("[yellow]هیچ نمادی شرایط ورود پول هوشمند برای نوسان‌گیری ۱ تا ۳ روزه را احراز نکرد.[/yellow]")

    # 5. PHASE 3: MULTI-REGIME DYNAMIC ASSET ALLOCATION
    if allocation_plan:
        console.print("\n[bold yellow]═══ ۵. تخصیص پویای دارایی میان ۴ طبقه اصلی (Phase 3 Multi-Regime Allocator) ═══[/bold yellow]")
        alloc_summary_text = (
            f"🧭 [bold]رژیم فعال بازار:[/bold] [bold cyan]{allocation_plan.regime.value}[/bold cyan]\n"
            f"📊 [bold]سطح ریسک:[/bold] {allocation_plan.risk_level}   |   "
            f"⚡ [bold]فوریت بازچینی:[/bold] {allocation_plan.rebalance_urgency}\n"
            f"💡 [dim]{allocation_plan.regime_rationale}[/dim]"
        )
        console.print(Panel(alloc_summary_text, title="🎯 برنامه بهینه وزن‌دهی سبد سرمایه‌گذاری", border_style="green"))

        alloc_table = Table(title="⚖️ توزیع درصدی سرمایه و نمادهای منتخب هر طبقه دارایی", header_style="bold green")
        alloc_table.add_column("طبقه دارایی", justify="right", style="bold white")
        alloc_table.add_column("وزن پیشنهادی (%)", justify="center", style="bold magenta")
        alloc_table.add_column("نماد منتخب", justify="center", style="bold yellow")
        alloc_table.add_column("نام صندوق / سهم", justify="right")
        alloc_table.add_column("منطق تخصیص و مدیریت ریسک", justify="right")

        for a in allocation_plan.allocations:
            alloc_table.add_row(
                a.asset_class,
                f"{a.target_weight_pct:.0f}%",
                a.recommended_symbol,
                a.recommended_name,
                a.rationale
            )
        console.print(alloc_table)

    console.print("\n" + "═" * 80 + "\n")


def run_scanner(use_demo: bool = False):
    """
    Executes the complete market scan and analysis workflow.
    """
    console.print("[bold green]🚀 در حال شروع اسکن بازار بورس تهران...[/bold green]")

    if use_demo:
        console.print("[cyan]اطلاعات آزمایشی (Demo Dataset) بارگذاری شد.[/cyan]")
        df = create_demo_dataset()
    else:
        client = TSETMCClient()
        console.print("[cyan]در حال دریافت داده‌های زنده دیده‌بان بازار و حقیقی/حقوقی از TSETMC...[/cyan]")
        df = client.get_full_market_snapshot()
        if df.empty:
            console.print("[red]⚠️ دریافت اطلاعات از TSETMC با خطا مواجه شد. بارگذاری حالت دمو به عنوان جایگزین...[/red]")
            df = create_demo_dataset()

    # 1. Tag Asset Classes
    df = FundTracker.tag_dataframe(df)

    # 2. Macro Flow Analysis
    macro_analyzer = MacroFlowAnalyzer()
    macro_report = macro_analyzer.analyze(df)

    # 3. Sector Rotation Analysis
    sector_analyzer = SectorRotationAnalyzer()
    sector_summaries = sector_analyzer.analyze(df)

    # 4. Phase 1 Refinements: Synthetic NAV & Lagging Detector
    val_detector = ValuationLaggingDetector(min_trade_value_b_toman=10.0)
    val_report = val_detector.analyze(df)

    # 5. Stock-Level Smart Money Screener
    screener = SmartMoneyScreener()
    top_sectors = [s.sector_name for s in sector_summaries if s.net_real_inflow_b_toman > 0][:5]
    candidates = screener.screen(df, top_sectors=top_sectors)

    # 6. Signal Generator (1-3 Day Horizon)
    signal_gen = SignalGenerator()
    action_plan = signal_gen.generate(
        macro_report=macro_report,
        sector_summaries=sector_summaries,
        candidates=candidates
    )

    # 7. Phase 2: FX Macro & Dirham Parity Radar
    fx_snap = None
    dirham_spread = 0.0
    try:
        fx_radar = FXMacroRadar()
        fx_snap = fx_radar.analyze_macro_spread()
        if fx_snap:
            dirham_spread = fx_snap.dirham_arbitrage_spread_pct
    except Exception as e:
        console.print(f"[dim yellow]⚠️ دریافت داده‌های ارزی با خطا مواجه شد: {e}[/dim yellow]")

    # 8. Phase 3: Multi-Regime Dynamic Asset Allocator
    allocator = MultiRegimeAssetAllocator()
    best_gold_sym = val_report.best_gold_fund.symbol if val_report.best_gold_fund else "عیار"
    best_gold_nm = val_report.best_gold_fund.name if val_report.best_gold_fund else "صندوق طلای عیار مفید"
    top_lev_sym = val_report.top_catch_up_leveraged.symbol if val_report.top_catch_up_leveraged else "شتاب"
    top_lev_nm = val_report.top_catch_up_leveraged.name if val_report.top_catch_up_leveraged else "صندوق شتاب مفید"
    top_stock_sym = candidates[0].symbol if candidates else "فولاد"
    top_stock_nm = candidates[0].name if candidates else "فولاد مبارکه اصفهان"

    eq_summary = macro_report.asset_summaries.get("سهام و حق تقدم")
    lev_summary = macro_report.asset_summaries.get("صندوق اهرمی")
    gold_summary = macro_report.asset_summaries.get("صندوق طلا")

    eq_inflow = (eq_summary.net_real_inflow_b_toman if eq_summary else 0.0) + (lev_summary.net_real_inflow_b_toman if lev_summary else 0.0)
    eq_power = eq_summary.avg_buyer_power if eq_summary else 1.0
    gold_inflow = gold_summary.net_real_inflow_b_toman if gold_summary else 0.0

    allocation_plan = allocator.generate_plan(
        equity_net_inflow_b_toman=eq_inflow,
        buyer_power_ratio=eq_power,
        dirham_spread_pct=dirham_spread,
        best_gold_symbol=best_gold_sym,
        best_gold_name=best_gold_nm,
        catch_up_leveraged_symbol=top_lev_sym,
        catch_up_leveraged_name=top_lev_nm,
        top_stock_symbol=top_stock_sym,
        top_stock_name=top_stock_nm,
        gold_flow_b_toman=gold_inflow
    )

    # 9. Render Terminal Dashboard
    display_dashboard(
        macro_report,
        sector_summaries,
        val_report,
        candidates,
        action_plan,
        fx_snap=fx_snap,
        allocation_plan=allocation_plan
    )


def main():
    parser = argparse.ArgumentParser(description="Iranian Market Smart Money & Capital Rotation Engine")
    parser.add_argument("--demo", action="store_true", help="Run with realistic demo dataset (offline mode)")
    args = parser.parse_args()

    run_scanner(use_demo=args.demo)


if __name__ == "__main__":
    main()
