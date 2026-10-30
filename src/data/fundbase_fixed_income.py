"""
Fundbase Fixed Income Client (صندوق‌های درآمد ثابت در فاندبیس)
Fetches reserve ratio (zakhireh - ذخیره کاهش ارزش دارایی‌ها و بافر سود تقسیمی)
from Fundbase's 'zakhireh_fixincome' table to detect financially resilient fixed income funds.
"""

import json
import urllib.request
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class FundbaseFixedIncomeMetrics:
    fund_id: str
    symbol: str
    date: str
    zakhireh: float  # Reserve amount / percentage buffer


class FundbaseFixedIncomeClient:
    SUPABASE_URL = "https://fyeguwhlfqhomqpkbgxb.supabase.co"
    API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5ZWd1d2hsZnFob21xcGtiZ3hiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDcwNjcyNjUsImV4cCI6MjA2MjY0MzI2NX0.LldFbOUTURJDOvhT57zB7-0CsGhgJyerIpuiBY_73w0"

    def __init__(self, timeout: int = 8):
        self.timeout = timeout
        self.proxy_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"})
        )
        self.direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get_latest_reserves(self, limit: int = 200) -> Dict[str, FundbaseFixedIncomeMetrics]:
        """
        Fetches the latest reserve (zakhireh) data for fixed income funds.
        Returns a mapping of symbol/name -> FundbaseFixedIncomeMetrics.
        """
        url = f"{self.SUPABASE_URL}/rest/v1/zakhireh_fixincome?select=fund_id,zakhireh,date,funds(id,name,slug)&order=date.desc&limit={limit}"
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
            print(f"Error fetching zakhireh_fixincome: {last_err}")
            return {}

        results: Dict[str, FundbaseFixedIncomeMetrics] = {}
        for row in data:
            finfo = row.get("funds") or {}
            fname = str(finfo.get("name", "")).strip()
            fid = str(row.get("fund_id", "")).strip()
            zakhireh_raw = row.get("zakhireh")
            if not fid or fid in [m.fund_id for m in results.values()] or zakhireh_raw is None:
                continue

            try:
                z_val = float(zakhireh_raw)
            except (ValueError, TypeError):
                continue

            results[fname] = FundbaseFixedIncomeMetrics(
                fund_id=fid,
                symbol=fname,
                date=str(row.get("date", "")),
                zakhireh=z_val
            )

        return results


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    client = FundbaseFixedIncomeClient()
    reserves = client.get_latest_reserves()
    print(f"Loaded {len(reserves)} fixed income funds with reserve data from Fundbase:")
    sorted_by_reserve = sorted(reserves.values(), key=lambda x: x.zakhireh, reverse=True)
    for m in sorted_by_reserve[:10]:
        print(f"  {m.symbol:25s} | ذخیره سود: {m.zakhireh:10.2f} | تاریخ: {m.date}")
