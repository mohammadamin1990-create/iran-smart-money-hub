"""
Phase 2: Macro & Currency Radar (رادار نرخ برابری درهم/دلار و حباب ارزی طلا)
Monitors Dubai Dirham (AED) to Tehran Free Dollar parity:
    USD_implied = AED_spot * 3.6725
    Spread% = ((USD_implied - USD_spot) / USD_spot) * 100
Detects institutional lead/lag arbitrage between Dubai remittance and Tehran cash market,
and computes implied dollar across Gold Funds, 18K Gold, and Emami Coins.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import urllib.request
import json


@dataclass
class AssetDollarBase:
    asset_name: str
    implied_dollar_rials: float
    premium_to_spot_pct: float
    status: str


@dataclass
class FXMacroRadarSnapshot:
    spot_usd_rials: float
    spot_aed_rials: float
    implied_usd_from_aed: float
    dirham_arbitrage_spread_pct: float
    macro_regime_signal: str
    macro_verdict: str
    asset_dollar_bases: List[AssetDollarBase]
    cheapest_dollar_asset: str
    gold_fund_vs_spot_usd_pct: float


class FXMacroRadar:
    AED_PEG_RATIO = 3.6725  # Fixed peg: 1 USD = 3.6725 AED
    SUPABASE_URL = "https://fyeguwhlfqhomqpkbgxb.supabase.co"
    API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5ZWd1d2hsZnFob21xcGtiZ3hiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDcwNjcyNjUsImV4cCI6MjA2MjY0MzI2NX0.LldFbOUTURJDOvhT57zB7-0CsGhgJyerIpuiBY_73w0"

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.proxy_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"})
        )
        self.direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.headers = {
            "apikey": self.API_KEY,
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }

    def _open_json(self, url: str):
        last_err = None
        for opener in (self.proxy_opener, self.direct_opener):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with opener.open(req, timeout=self.timeout) as res:
                    return json.loads(res.read().decode("utf-8"))
            except Exception as e:
                last_err = e
        raise last_err

    def fetch_live_fx_data(self) -> Dict[str, float]:
        """
        Fetches latest currency market rates from currency_market_map.
        """
        url = f"{self.SUPABASE_URL}/rest/v1/currency_market_map?select=symbol,last_price"
        rates = {}
        try:
            data = self._open_json(url)
            for row in data:
                sym = str(row.get("symbol", "")).strip()
                price = float(row.get("last_price", 0.0) or 0.0)
                if sym and price > 0:
                    rates[sym] = price
        except Exception as e:
            print(f"Error fetching currency_market_map: {e}")
        return rates

    def fetch_dollarbase_bubbles(self) -> List[Dict[str, any]]:
        """
        Fetches implied dollar prices for gold assets from dollarbase_bubble.
        """
        url = f"{self.SUPABASE_URL}/rest/v1/dollarbase_bubble?select=symbol,dollarbase_price,last_update"
        try:
            return self._open_json(url)
        except Exception as e:
            print(f"Error fetching dollarbase_bubble: {e}")
            return []

    def analyze_macro_spread(
        self,
        manual_spot_usd: Optional[float] = None,
        manual_spot_aed: Optional[float] = None
    ) -> FXMacroRadarSnapshot:
        """
        Performs full Dirham/Dollar parity and Gold asset implied dollar valuation.
        """
        fx_rates = self.fetch_live_fx_data()
        dollarbase_data = self.fetch_dollarbase_bubbles()

        spot_usd = manual_spot_usd or fx_rates.get("دلار", 271060.0)
        spot_aed = manual_spot_aed or fx_rates.get("درهم امارات", 74289.0)

        # Implied Dollar from Dubai Dirham
        implied_usd = spot_aed * self.AED_PEG_RATIO
        spread_pct = ((implied_usd - spot_usd) / spot_usd) * 100.0 if spot_usd > 0 else 0.0

        # Macro Regime Classification
        if spread_pct > 0.7:
            regime = "🟢 صعودی (Bullish USD/Gold)"
            verdict = (
                f"پیشتازی حواله درهم ({spread_pct:+.2f}٪ نسبت به دلار تهران)؛ "
                "فشار خرید از دبی به بازار تهران تزریق می‌شود. سیگنال مثبت برای صندوق‌های طلا."
            )
        elif spread_pct < -0.7:
            regime = "🔴 اصلاحی / کاهشی (Bearish USD/Gold)"
            verdict = (
                f"افت درهم دبی نسبت به دلار فردوسی ({spread_pct:+.2f}٪)؛ "
                "ریسک اصلاح قیمت دلار نقدی و تخلیه حباب در صندوق‌های طلا."
            )
        else:
            regime = "⚪ متعادل و پایدار (Neutral Range)"
            verdict = (
                f"تطابق نرخ برابری درهم و دلار ({spread_pct:+.2f}٪)؛ "
                "بازار ارز در وضعیت تعادلی و بدون آربیتراژ فعال."
            )

        # Process Dollar Base assets
        dollar_assets: List[AssetDollarBase] = []
        gold_fund_vs_spot = 0.0

        for row in dollarbase_data:
            name = str(row.get("symbol", "")).strip()
            db_price = float(row.get("dollarbase_price", 0.0) or 0.0)
            if db_price <= 0:
                continue

            prem = ((db_price - spot_usd) / spot_usd) * 100.0 if spot_usd > 0 else 0.0

            if prem < -0.5:
                status = "🟢 ارزان‌تر از دلار آزاد (Discount - Buy)"
            elif prem <= 2.0:
                status = "⚪ هم‌تراز با دلار آزاد (Fair)"
            elif prem <= 6.0:
                status = "🟡 حباب متعارف (Moderate Premium)"
            else:
                status = "🔴 حباب شدید و سفته‌بازی (High Bubble)"

            if "صندوق" in name:
                gold_fund_vs_spot = prem

            dollar_assets.append(
                AssetDollarBase(
                    asset_name=name,
                    implied_dollar_rials=round(db_price, 0),
                    premium_to_spot_pct=round(prem, 2),
                    status=status
                )
            )

        # Sort dollar assets ascending by implied dollar (cheapest first)
        dollar_assets.sort(key=lambda x: x.implied_dollar_rials)
        cheapest = dollar_assets[0].asset_name if dollar_assets else "نامشخص"

        return FXMacroRadarSnapshot(
            spot_usd_rials=round(spot_usd, 0),
            spot_aed_rials=round(spot_aed, 0),
            implied_usd_from_aed=round(implied_usd, 0),
            dirham_arbitrage_spread_pct=round(spread_pct, 2),
            macro_regime_signal=regime,
            macro_verdict=verdict,
            asset_dollar_bases=dollar_assets,
            cheapest_dollar_asset=cheapest,
            gold_fund_vs_spot_usd_pct=round(gold_fund_vs_spot, 2)
        )


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    radar = FXMacroRadar()
    snap = radar.analyze_macro_spread()
    print("=" * 65)
    print("      رادار کلان نرخ برابری درهم و دلار تهران (Phase 2 FX Radar)")
    print("=" * 65)
    print(f"💵 دلار آزاد تهران:       {snap.spot_usd_rials:,.0f} ریال")
    print(f"🇦🇪 درهم حواله دبی:        {snap.spot_aed_rials:,.0f} ریال")
    print(f"📐 دلار محاسباتی از درهم:  {snap.implied_usd_from_aed:,.0f} ریال")
    print(f"⚡ اسپرد آربیتراژ درهم:    {snap.dirham_arbitrage_spread_pct:+5.2f}%")
    print(f"🧭 وضعیت رژیم کلان:       {snap.macro_regime_signal}")
    print(f"📝 تحلیل و توصیه:         {snap.macro_verdict}")
    print("-" * 65)
    print("جدول دلار محاسباتی دارایی‌های طلامحور (رتبه‌بندی از ارزان‌ترین):")
    for a in snap.asset_dollar_bases:
        print(f"  {a.asset_name:22s} | دلار محاسباتی: {a.implied_dollar_rials:>10,.0f} ریال ({a.premium_to_spot_pct:+5.1f}%) | {a.status}")
    print("=" * 65)
