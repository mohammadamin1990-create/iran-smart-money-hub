"""
Fundbase Portfolio Search & Institutional Accumulation Engine
(پایش اقدامات تجمیعی صندوق‌ها، بیشترین خریدهای حقوقی و روند تغییر وزن سهام)
"""
import urllib.request
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class TopFundTradeItem:
    name: str              # Symbol or Industry name
    net_value_rial: float  # Net buying amount (purchase - sale)
    purchase_value_rial: float
    sale_value_rial: float
    start_weight: float    # Weight in funds portfolio at start of period
    end_weight: float      # Weight in funds portfolio at end of period
    weight_change: float   # Net change in portfolio weight percentage
    buyer_count: int       # Number of funds actively buying
    total_funds_holding: int
    period_start: str      # e.g. "1405/04"
    period_end: str        # e.g. "1405/07"

    @property
    def net_value_hemmat(self) -> float:
        # 1 Hemmat = 10^13 Rials (10,000 Billion Rials / 1,000 Billion Tomans)
        return self.net_value_rial / 10_000_000_000_000

    @property
    def net_value_billion_toman(self) -> float:
        return self.net_value_rial / 10_000_000_000

    @property
    def is_accumulating(self) -> bool:
        return self.net_value_rial > 0 and self.weight_change > 0


@dataclass
class SymbolWeightPoint:
    report_date: str  # e.g. "1405/07"
    weight_pct: float


class FundbasePortfolioSearchClient:
    SUPABASE_URL = "https://fyeguwhlfqhomqpkbgxb.supabase.co"
    ANON_KEY = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5ZWd1d2hsZnFob21xcGtiZ3hiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDcwNjcyNjUsImV4cCI6MjA2MjY0MzI2NX0."
        "LldFbOUTURJDOvhT57zB7-0CsGhgJyerIpuiBY_73w0"
    )

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.proxy_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"})
        )
        self.direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _call_rpc(self, rpc_name: str, payload: dict) -> Any:
        url = f"{self.SUPABASE_URL}/rest/v1/rpc/{rpc_name}"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "apikey": self.ANON_KEY,
            "Authorization": f"Bearer {self.ANON_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        last_err = None
        for opener in (self.proxy_opener, self.direct_opener):
            try:
                req = urllib.request.Request(url, headers=headers, data=data)
                with opener.open(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                last_err = e
        raise last_err

    def get_top_fund_buys(
        self,
        months: int = 3,
        level: str = "symbol",  # "symbol" or "industry"
        metric: str = "amount",  # "amount" or "weight"
        direction: str = "buy",  # "buy" or "sell"
        limit: int = 20,
        category_ids: Optional[List[str]] = None,
        fund_ids: Optional[List[str]] = None,
    ) -> List[TopFundTradeItem]:
        """
        Retrieves the top bought or sold stocks/industries across funds.
        """
        payload = {
            "p_months": months,
            "p_level": level,
            "p_metric": metric,
            "p_direction": direction,
            "p_limit": limit,
            "p_category_ids": category_ids,
            "p_fund_ids": fund_ids,
        }
        raw = self._call_rpc("get_top_fund_buys", payload)
        items = []
        for r in raw:
            items.append(
                TopFundTradeItem(
                    name=r.get("key_name", "").strip(),
                    net_value_rial=float(r.get("net_value") or 0.0),
                    purchase_value_rial=float(r.get("purchase_value") or 0.0),
                    sale_value_rial=float(r.get("sale_value") or 0.0),
                    start_weight=float(r.get("start_weight") or 0.0),
                    end_weight=float(r.get("end_weight") or 0.0),
                    weight_change=float(r.get("weight_change") or 0.0),
                    buyer_count=int(r.get("buyer_count") or 0),
                    total_funds_holding=int(r.get("fund_count") or 0),
                    period_start=r.get("start_month", ""),
                    period_end=r.get("end_month", ""),
                )
            )
        return items

    def get_symbol_weight_history(self, symbol: str) -> List[SymbolWeightPoint]:
        """Fetches historical portfolio weight percentage of a symbol in all funds."""
        raw = self._call_rpc("get_symbol_weight_history", {"p_symbol": symbol.strip()})
        points = []
        for r in raw:
            points.append(
                SymbolWeightPoint(
                    report_date=r.get("report_date", ""),
                    weight_pct=float(r.get("weight") or 0.0),
                )
            )
        return points

    def calculate_stock_institutional_conviction(
        self, symbol: str, months: int = 3
    ) -> Dict[str, Any]:
        """
        Computes an Institutional Conviction Score (0-100) for an individual stock.
        Combines:
        1. Net buying magnitude by funds.
        2. Positive weight expansion in funds.
        3. Trend in recent 3-5 monthly weight points.
        """
        top_buys = self.get_top_fund_buys(months=months, level="symbol", limit=50)
        found_item = next((b for b in top_buys if b.name == symbol), None)
        history = self.get_symbol_weight_history(symbol)

        score = 50.0  # Base neutral score
        metrics = {
            "symbol": symbol,
            "is_top_accumulated": False,
            "net_buying_hemmat": 0.0,
            "weight_change_pct": 0.0,
            "buyer_funds_count": 0,
            "consecutive_monthly_accumulation": False,
            "conviction_score": 50.0,
            "verdict": "خنثی / بدون انباشت خاص",
        }

        if found_item:
            metrics["is_top_accumulated"] = True
            metrics["net_buying_hemmat"] = round(found_item.net_value_hemmat, 2)
            metrics["weight_change_pct"] = round(found_item.weight_change, 3)
            metrics["buyer_funds_count"] = found_item.buyer_count

            # Up to +30 points for heavy net buying
            buying_bonus = min(30.0, (found_item.net_value_hemmat / 10.0) * 10.0)
            # Up to +15 points for positive weight change
            weight_bonus = min(15.0, max(0.0, found_item.weight_change * 30.0))
            score += (buying_bonus + weight_bonus)

        # Check consecutive monthly weight trend
        if len(history) >= 3:
            recent_weights = [pt.weight_pct for pt in history[-3:]]
            if recent_weights[0] < recent_weights[1] < recent_weights[2]:
                metrics["consecutive_monthly_accumulation"] = True
                score += 15.0  # +15 points for consistent uptrend in institutional allocation

        score = min(100.0, max(0.0, score))
        metrics["conviction_score"] = round(score, 1)

        if score >= 75.0:
            metrics["verdict"] = "🔥 انباشت سنگین و اجماع حقوقی (Strong Institutional Accumulation)"
        elif score >= 60.0:
            metrics["verdict"] = "🟢 انباشت مثبت (Moderate Accumulation)"
        elif score <= 40.0:
            metrics["verdict"] = "🔴 خروج یا کاهش وزن حقوقی (Distribution)"

        return metrics

    @staticmethod
    def score_fund_alignment_with_top_buys(
        fund_holdings: Dict[str, float], top_buys: List[TopFundTradeItem]
    ) -> float:
        """
        Scores how well a fund's portfolio aligns with the stocks being accumulated
        by the broader institutional community (0-100).
        """
        if not fund_holdings or not top_buys:
            return 50.0

        top_accumulated_symbols = {
            b.name: b.net_value_hemmat for b in top_buys if b.is_accumulating
        }
        total_aligned_weight = 0.0

        for sym, weight in fund_holdings.items():
            if sym in top_accumulated_symbols:
                total_aligned_weight += weight

        # If a fund has > 40% of its portfolio in the top consensus accumulated stocks -> 100 score
        alignment_score = min(100.0, (total_aligned_weight / 40.0) * 100.0)
        return round(alignment_score, 1)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    client = FundbasePortfolioSearchClient()

    print("=== ۵ سهم با بیشترین خالص خرید صندوق‌ها در ۳ ماه گذشته ===")
    top_buys = client.get_top_fund_buys(months=3, limit=5)
    for b in top_buys:
        print(f"نماد: {b.name:<8} | برآیند خرید: {b.net_value_hemmat:+.2f} همت | تغییر وزن: {b.weight_change:+.2f}% | خریداران: {b.buyer_count} صندوق")

    print("\n=== تحلیل همگرایی حقوقی روی نماد فولاد ===")
    foulad_metrics = client.calculate_stock_institutional_conviction("فولاد", months=3)
    for k, v in foulad_metrics.items():
        print(f"• {k}: {v}")

    print("\n=== تحلیل همگرایی حقوقی روی نماد فملی ===")
    femeli_metrics = client.calculate_stock_institutional_conviction("فملی", months=3)
    for k, v in femeli_metrics.items():
        print(f"• {k}: {v}")
