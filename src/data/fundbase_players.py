"""
Client for Fundbase Tracked Investors (Players / بازیکنان)
"""
import urllib.request
import json
from typing import List, Dict, Optional, Any
from dataclasses import dataclass


@dataclass
class PlayerTransaction:
    alias_id: int
    alias: str
    date: str
    symbol: str
    shares_change: int
    number_of_shares: int
    percent_of_shares: float
    value_rial: float

    @property
    def value_billion_toman(self) -> float:
        return self.value_rial / 10_000_000_000

    @property
    def is_buy(self) -> bool:
        return self.shares_change > 0


@dataclass
class PlayerCard:
    alias_id: int
    alias: str
    portfolio_value_rial: float
    symbol_count: int
    last_activity: str
    top_symbol: str

    @property
    def portfolio_value_hemmat(self) -> float:
        # 1 Hemmat = 10^12 Rials (1000 Billion Tomans)
        return self.portfolio_value_rial / 10_000_000_000_000


class FundbasePlayersClient:
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

    def get_top_players(self, limit: int = 500) -> List[PlayerCard]:
        """Fetches the top tracked players (investors) ranking."""
        raw = self._call_rpc("get_tracked_investors", {})
        players = []
        for r in raw[:limit]:
            players.append(
                PlayerCard(
                    alias_id=r.get("alias_id", 0),
                    alias=r.get("alias", ""),
                    portfolio_value_rial=float(r.get("portfolio_value", 0)),
                    symbol_count=int(r.get("symbol_count", 0)),
                    last_activity=r.get("last_activity", ""),
                    top_symbol=r.get("top_symbol", ""),
                )
            )
        return players

    def get_latest_transactions(
        self, limit: int = 50, alias_id: Optional[int] = None
    ) -> List[PlayerTransaction]:
        """Fetches live stream of buys and sells by tracked players."""
        payload = {"p_alias_id": alias_id, "p_limit": limit}
        raw = self._call_rpc("get_tracked_investor_feed", payload)
        txs = []
        for r in raw:
            txs.append(
                PlayerTransaction(
                    alias_id=r.get("alias_id", 0),
                    alias=r.get("alias", ""),
                    date=r.get("date", ""),
                    symbol=r.get("symbol", ""),
                    shares_change=int(r.get("shares_change", 0)),
                    number_of_shares=int(r.get("number_of_shares", 0)),
                    percent_of_shares=float(r.get("percent_of_shares", 0)),
                    value_rial=float(r.get("value_rial", 0)),
                )
            )
        return txs

    def get_player_holdings(self, alias_id: int) -> List[Dict[str, Any]]:
        """Fetches all assets currently held in a specific player's portfolio."""
        return self._call_rpc("get_tracked_investor_holdings", {"p_alias_id": alias_id})


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    client = FundbasePlayersClient()
    txs = client.get_latest_transactions(limit=5)
    print(f"Fetched {len(txs)} transactions successfully.")
    for t in txs:
        action = "🟢 BUY" if t.is_buy else "🔴 SELL"
        print(f"[{t.date}] {action} {t.alias} -> {t.symbol} ({t.value_billion_toman:+.2f} B Toman)")
    
    players = client.get_top_players(limit=3)
    print(f"\nTop {len(players)} Players:")
    for p in players:
        print(f"Rank {p.alias_id}: {p.alias} | Portfolio: {p.portfolio_value_hemmat:.1f} Hemmat | Top Symbol: {p.top_symbol}")
