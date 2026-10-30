"""
Fundbase Leveraged Funds Client (صندوق‌های اهرمی در فاندبیس)
Fetches dynamic leverage ratios (real_ratio, nominal_ratio) and price bubbles (price_bubble)
from Fundbase's dedicated 'leveraged_funds_data' table.
"""

import json
import urllib.request
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class FundbaseLeveragedMetrics:
    fund_id: str
    symbol: str
    date: str
    real_ratio: float
    nominal_ratio: float
    price_bubble: float


class FundbaseLeveragedClient:
    SUPABASE_URL = "https://fyeguwhlfqhomqpkbgxb.supabase.co"
    API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5ZWd1d2hsZnFob21xcGtiZ3hiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDcwNjcyNjUsImV4cCI6MjA2MjY0MzI2NX0.LldFbOUTURJDOvhT57zB7-0CsGhgJyerIpuiBY_73w0"

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.proxy_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"})
        )
        self.direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get_latest_leveraged_metrics(self) -> Dict[str, FundbaseLeveragedMetrics]:
        """
        Fetches the latest leveraged fund ratios and price bubbles.
        Returns a mapping of symbol/name -> FundbaseLeveragedMetrics.
        """
        url = f"{self.SUPABASE_URL}/rest/v1/leveraged_funds_data?select=*,funds!inner(id,name,slug)&order=date.desc&limit=100"
        headers = {
            "apikey": self.API_KEY,
            "Authorization": f"Bearer {self.API_KEY}",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0"
        }
        data = None
        last_err = None
        for opener in (self.proxy_opener, self.direct_opener):
            try:
                req = urllib.request.Request(url, headers=headers)
                with opener.open(req, timeout=self.timeout) as res:
                    data = json.loads(res.read().decode("utf-8"))
                    break
            except Exception as e:
                last_err = e
        if data is None:
            print(f"Error fetching leveraged_funds_data: {last_err}")
            return {}

        results: Dict[str, FundbaseLeveragedMetrics] = {}
        for row in data:
            finfo = row.get("funds") or {}
            fname = str(finfo.get("name", "")).strip()
            fid = str(row.get("fund_id", "")).strip()
            if not fid or fid in [m.fund_id for m in results.values()]:
                continue

            # Extract clean symbol / ticker from fund name (e.g. "شتاب", "اهرم", "جهش")
            symbol = fname
            results[symbol] = FundbaseLeveragedMetrics(
                fund_id=fid,
                symbol=symbol,
                date=str(row.get("date", "")),
                real_ratio=float(row.get("real_ratio", 0.0) or 0.0),
                nominal_ratio=float(row.get("nominal_ratio", 0.0) or 0.0),
                price_bubble=float(row.get("price_bubble", 0.0) or 0.0)
            )

        return results


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    client = FundbaseLeveragedClient()
    metrics = client.get_latest_leveraged_metrics()
    print(f"Loaded {len(metrics)} leveraged funds from Fundbase:")
    for sym, m in metrics.items():
        print(f"  {sym:12s} | اهرم واقعی: {m.real_ratio:.2f} | اهرم اسمی: {m.nominal_ratio:.2f} | حباب: {m.price_bubble:+5.2f}%")
