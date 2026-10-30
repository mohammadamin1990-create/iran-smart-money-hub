"""
Fundbase Gold Metrics Client (صندوق‌های طلا در فاندبیس)
Fetches triple bubble (price_bubble, inherent_bubble, total_bubble),
composition (bar, coin, silver), and issuance capacity (سقف صدور واحدها).
"""

import json
import urllib.request
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class FundbaseGoldMetrics:
    symbol: str
    date: str
    close_price: float
    redemption_nav: float
    price_bubble: float
    inherent_bubble: float
    total_bubble: float
    gold_bar_bubble: float
    gold_coin_bubble: float
    bar_pct: float
    coin_pct: float
    silver_pct: float
    other_pct: float
    remained_capacity: Optional[float] = None


class FundbaseGoldClient:
    SUPABASE_URL = "https://fyeguwhlfqhomqpkbgxb.supabase.co"
    API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5ZWd1d2hsZnFob21xcGtiZ3hiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDcwNjcyNjUsImV4cCI6MjA2MjY0MzI2NX0.LldFbOUTURJDOvhT57zB7-0CsGhgJyerIpuiBY_73w0"

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.proxy_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"})
        )
        self.direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _open_json(self, url: str):
        headers = {
            "apikey": self.API_KEY,
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        last_err = None
        for opener in (self.proxy_opener, self.direct_opener):
            try:
                req = urllib.request.Request(url, headers=headers)
                with opener.open(req, timeout=self.timeout) as res:
                    return json.loads(res.read().decode("utf-8"))
            except Exception as e:
                last_err = e
        raise last_err

    def get_latest_gold_metrics(self) -> Dict[str, FundbaseGoldMetrics]:
        """
        Fetches the latest metrics for all gold funds from gold_fund_data.
        Returns a mapping of symbol -> FundbaseGoldMetrics.
        """
        url = f"{self.SUPABASE_URL}/rest/v1/gold_fund_data?select=*&order=date.desc&limit=100"
        try:
            data = self._open_json(url)
        except Exception as e:
            print(f"Error fetching gold_fund_data: {e}")
            return {}

        results: Dict[str, FundbaseGoldMetrics] = {}
        for row in data:
            sym = str(row.get("symbol", "")).strip()
            if not sym or sym in results:
                continue

            results[sym] = FundbaseGoldMetrics(
                symbol=sym,
                date=str(row.get("date", "")),
                close_price=float(row.get("close", 0.0) or 0.0),
                redemption_nav=float(row.get("redemption_nav", 0.0) or 0.0),
                price_bubble=float(row.get("price_bubble", 0.0) or 0.0),
                inherent_bubble=float(row.get("inherent_bubble", 0.0) or 0.0),
                total_bubble=float(row.get("total_bubble", 0.0) or 0.0),
                gold_bar_bubble=float(row.get("gold_bar_bubble", 0.0) or 0.0),
                gold_coin_bubble=float(row.get("gold_coin_bubble", 0.0) or 0.0),
                bar_pct=float(row.get("adjusted_sum_bar_percentage", 0.0) or 0.0),
                coin_pct=float(row.get("adjusted_sum_coin_percentage", 0.0) or 0.0),
                silver_pct=float(row.get("adjusted_sum_silver_percentage", 0.0) or 0.0),
                other_pct=float(row.get("other_percentage", 0.0) or 0.0)
            )

        # Also attempt to attach capacity if available
        self._attach_issuance_capacity(results)
        return results

    def _attach_issuance_capacity(self, metrics: Dict[str, FundbaseGoldMetrics]) -> None:
        """
        Fetches latest fund_unit_issuance_capacity and updates metrics.
        """
        url = f"{self.SUPABASE_URL}/rest/v1/fund_unit_issuance_capacity?select=fund_id,fund_unit_issuance_capacity,date,funds(name,slug)&order=date.desc&limit=150"
        try:
            data = self._open_json(url)
            seen_funds = set()
            for row in data:
                fid = row.get("fund_id")
                if fid in seen_funds:
                    continue
                seen_funds.add(fid)
                finfo = row.get("funds") or {}
                fname = finfo.get("name", "")
                slug = finfo.get("slug", "")
                cap = float(row.get("fund_unit_issuance_capacity", 0.0) or 0.0)

                for sym, met in metrics.items():
                    if sym in fname or sym in slug:
                        met.remained_capacity = cap
        except Exception as e:
            # Capacity is optional enhancement
            pass


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    client = FundbaseGoldClient()
    gold_data = client.get_latest_gold_metrics()
    print(f"Loaded {len(gold_data)} gold funds from Fundbase:")
    for sym, m in list(gold_data.items())[:6]:
        print(f"  {sym:8s} | حباب کل: {m.total_bubble:+5.1f}% (قیمتی: {m.price_bubble:+5.1f}% | ذاتی: {m.inherent_bubble:+5.1f}%) | شمش: {m.bar_pct:4.1f}% | سکه: {m.coin_pct:4.1f}%")
