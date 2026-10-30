"""
Fundbase Screener & Smart Ranker Client
(ادغام تداوم بازدهی Consistency و پویایی مدیر Turnover در غربالگری صندوق‌ها)
"""
import urllib.request
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class FundScreenerMetric:
    fund_id: str
    symbol: str
    name: str
    category_id: str
    category_name: str
    consistency_score: float  # تداوم بازدهی (0 to 100)
    consistency_rank: int     # رتبه تداوم در دسته
    turnover_pct_3m: float    # درصد گردش پورتفوی ۳ ماهه (مدیریت فعال)
    bubble_pct: float         # حباب P/NAV
    net_asset_rial: float     # خالص دارایی (AUM)
    trading_value_rial: float # ارزش معاملات روزانه
    alpha: float
    beta: float
    return_monthly: Optional[float]
    return_quarterly: Optional[float]
    return_biannual: Optional[float]
    return_yearly: Optional[float]

    @property
    def aum_hemmat(self) -> float:
        return self.net_asset_rial / 10_000_000_000_000

    @property
    def trading_value_billion_toman(self) -> float:
        return self.trading_value_rial / 10_000_000_000


class FundbaseScreenerClient:
    SUPABASE_URL = "https://fyeguwhlfqhomqpkbgxb.supabase.co"
    ANON_KEY = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5ZWd1d2hsZnFob21xcGtiZ3hiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDcwNjcyNjUsImV4cCI6MjA2MjY0MzI2NX0."
        "LldFbOUTURJDOvhT57zB7-0CsGhgJyerIpuiBY_73w0"
    )

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _call_rpc(self, rpc_name: str, payload: dict) -> Any:
        url = f"{self.SUPABASE_URL}/rest/v1/rpc/{rpc_name}"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            headers={
                "apikey": self.ANON_KEY,
                "Authorization": f"Bearer {self.ANON_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            data=data,
        )
        with self.opener.open(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))

    def get_turnover_map(self, months: int = 3) -> Dict[str, float]:
        """Returns map of fund_id -> turnover_pct (گردش پورتفو در ۳ ماه اخیر)."""
        raw = self._call_rpc("get_all_funds_turnover", {"p_months": months})
        turnover_map = {}
        for r in raw:
            fid = r.get("fund_id")
            val = r.get("turnover_pct")
            if fid and val is not None:
                turnover_map[fid] = float(val)
        return turnover_map

    def get_consistency_map(self) -> Dict[str, Dict[str, Any]]:
        """Returns map of fund_id -> {consistency_score, rank_in_category, total_funds}."""
        raw = self._call_rpc("get_fund_return_consistency", {"p_category_id": None})
        consistency_map = {}
        for r in raw:
            fid = r.get("fund_id")
            if fid:
                consistency_map[fid] = {
                    "consistency_score": float(r.get("consistency_score") or 0.0),
                    "rank_in_category": int(r.get("rank_in_category") or 0),
                    "total_funds": int(r.get("total_funds") or 0),
                }
        return consistency_map

    def get_fund_screener_universe(
        self, fund_names_filter: Optional[List[str]] = None
    ) -> List[FundScreenerMetric]:
        """
        Gathers complete screener metrics:
        funds + turnover + consistency + live data + returns.
        """
        turnover_map = self.get_turnover_map(months=3)
        consistency_map = self.get_consistency_map()

        # Fetch funds metadata
        url_funds = f"{self.SUPABASE_URL}/rest/v1/funds?select=id,name,slug,category_id,category:categories(name)"
        req = urllib.request.Request(
            url_funds,
            headers={
                "apikey": self.ANON_KEY,
                "Authorization": f"Bearer {self.ANON_KEY}",
                "User-Agent": "Mozilla/5.0",
            },
        )
        with self.opener.open(req, timeout=self.timeout) as resp:
            funds_raw = json.loads(resp.read().decode("utf-8"))

        # Fetch live data for these funds
        url_live = f"{self.SUPABASE_URL}/rest/v1/fund_live_data?select=fund_id,bubble_percent,trading_value,net_asset,alpha,beta&order=timestamp.desc&limit=2000"
        req_live = urllib.request.Request(
            url_live,
            headers={
                "apikey": self.ANON_KEY,
                "Authorization": f"Bearer {self.ANON_KEY}",
                "User-Agent": "Mozilla/5.0",
            },
        )
        with self.opener.open(req_live, timeout=self.timeout) as resp:
            live_raw = json.loads(resp.read().decode("utf-8"))

        live_map = {}
        for l in live_raw:
            fid = l.get("fund_id")
            if fid and fid not in live_map:
                live_map[fid] = l

        results = []
        for f in funds_raw:
            name = (f.get("name") or "").strip()
            if fund_names_filter and name not in fund_names_filter:
                continue

            fid = f.get("id")
            c_info = consistency_map.get(fid, {})
            t_pct = turnover_map.get(fid, 0.0)
            l_info = live_map.get(fid, {})

            cat_dict = f.get("category") or {}
            cat_name = cat_dict.get("name", "نامشخص") if isinstance(cat_dict, dict) else "نامشخص"

            results.append(
                FundScreenerMetric(
                    fund_id=fid,
                    symbol=f.get("slug") or name,
                    name=name,
                    category_id=f.get("category_id") or "",
                    category_name=cat_name,
                    consistency_score=c_info.get("consistency_score", 50.0),
                    consistency_rank=c_info.get("rank_in_category", 0),
                    turnover_pct_3m=t_pct,
                    bubble_pct=float(l_info.get("bubble_percent") or 0.0),
                    net_asset_rial=float(l_info.get("net_asset") or 0.0),
                    trading_value_rial=float(l_info.get("trading_value") or 0.0),
                    alpha=float(l_info.get("alpha") or 0.0),
                    beta=float(l_info.get("beta") or 1.0),
                    return_monthly=None,
                    return_quarterly=None,
                    return_biannual=None,
                    return_yearly=None,
                )
            )

        return results

    @staticmethod
    def calculate_composite_quality_score(
        fund: FundScreenerMetric,
        w_consistency: float = 0.35,
        w_turnover: float = 0.25,
        w_low_bubble: float = 0.20,
        w_liquidity: float = 0.20,
    ) -> float:
        """
        Combines Consistency and Turnover with Bubble & Liquidity into a unified quality score (0-100).
        """
        # Consistency score is already 0-100
        c_score = fund.consistency_score

        # Turnover: ideally active (20% to 80% per quarter is healthy active management)
        # 40% turnover gets 100 points, 0% gets 20 points
        t_score = min(100.0, max(20.0, (fund.turnover_pct_3m / 40.0) * 100.0))

        # Bubble: lower is better. Bubble < 0% gets 100, 5% gets 70, 10% gets 40, >15% gets 10
        b_score = max(0.0, min(100.0, 100.0 - (fund.bubble_pct * 6.0)))

        # Liquidity: > 10 Billion Toman daily value is 100, 2B is 50, <0.5B is 10
        liq_score = min(100.0, max(10.0, (fund.trading_value_billion_toman / 10.0) * 100.0))

        total_score = (
            (w_consistency * c_score)
            + (w_turnover * t_score)
            + (w_low_bubble * b_score)
            + (w_liquidity * liq_score)
        )
        return round(total_score, 1)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    client = FundbaseScreenerClient()
    targets = ["اهرم", "شتاب", "جهش", "موج", "عیار", "کهربا", "طلا"]
    metrics = client.get_fund_screener_universe(fund_names_filter=targets)

    print(f"=== استخراج سنجه‌های تداوم بازدهی و پویایی مدیر برای {len(metrics)} صندوق هدف ===")
    for m in metrics:
        q_score = client.calculate_composite_quality_score(m)
        print(f"نماد: {m.name:<8} | ثبات بازدهی: {m.consistency_score:>5.1f}/100 (رتبه {m.consistency_rank}) | گردش پورتفو ۳م: {m.turnover_pct_3m:>5.1f}% | حباب: {m.bubble_pct:>+5.1f}% | امتیاز کیفیت: {q_score}/100")
