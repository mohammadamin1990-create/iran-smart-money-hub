"""
Fundbase Funds Overlap & Portfolio Concentration Risk Engine
"""
import urllib.request
import json
from typing import List, Dict, Set, Tuple, Optional, Any
from dataclasses import dataclass, field


@dataclass
class HoldingPosition:
    symbol: str
    industry: str
    fund_id: str
    weight: float


@dataclass
class OverlapPairResult:
    fund_a_id: str
    fund_a_name: str
    fund_b_id: str
    fund_b_name: str
    overlap_pct: float
    common_symbols_count: int
    top_common_symbols: List[Dict[str, Any]]
    is_redundant: bool  # True if overlap exceeds threshold (e.g. > 50%)


@dataclass
class PortfolioConcentrationAlert:
    severity: str  # "HIGH", "MEDIUM", "INFO"
    asset: str     # Symbol or Industry
    asset_type: str  # "STOCK" or "INDUSTRY"
    effective_weight_pct: float
    message: str


@dataclass
class OverlapReport:
    pairwise_overlaps: List[OverlapPairResult]
    common_consensus_symbols: List[Dict[str, Any]]
    concentration_alerts: List[PortfolioConcentrationAlert]
    recommended_pruned_funds: List[str]  # Funds recommended to remove due to redundancy


class FundbaseOverlapClient:
    SUPABASE_URL = "https://fyeguwhlfqhomqpkbgxb.supabase.co"
    ANON_KEY = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImZ5ZWd1d2hsZnFob21xcGtiZ3hiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NDcwNjcyNjUsImV4cCI6MjA2MjY0MzI2NX0."
        "LldFbOUTURJDOvhT57zB7-0CsGhgJyerIpuiBY_73w0"
    )

    def __init__(self, timeout: int = 12):
        self.timeout = timeout
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def get_funds_holdings_raw(self, fund_ids: List[str]) -> List[HoldingPosition]:
        """Calls get_funds_overlap RPC on Supabase to get portfolio holdings for all passed funds."""
        if not fund_ids:
            return []
        url = f"{self.SUPABASE_URL}/rest/v1/rpc/get_funds_overlap"
        payload = json.dumps({"p_fund_ids": fund_ids}).encode("utf-8")
        req = urllib.request.Request(
            url,
            headers={
                "apikey": self.ANON_KEY,
                "Authorization": f"Bearer {self.ANON_KEY}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            data=payload,
        )
        with self.opener.open(req, timeout=self.timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        positions = []
        for r in data:
            positions.append(
                HoldingPosition(
                    symbol=r.get("symbol", "").strip(),
                    industry=r.get("industry", "سایر").strip(),
                    fund_id=r.get("fund_id", ""),
                    weight=float(r.get("weight") or 0.0),
                )
            )
        return positions

    @staticmethod
    def calculate_pairwise_overlap(
        fund_a_positions: Dict[str, float],
        fund_b_positions: Dict[str, float],
    ) -> Tuple[float, List[Dict[str, Any]]]:
        """
        Calculates pairwise weighted minimum overlap:
        Overlap(A, B) = sum_{s in A cap B} min(w_A(s), w_B(s))
        """
        common_symbols = set(fund_a_positions.keys()) & set(fund_b_positions.keys())
        overlap_sum = 0.0
        details = []

        for sym in common_symbols:
            w_a = fund_a_positions[sym]
            w_b = fund_b_positions[sym]
            min_w = min(w_a, w_b)
            overlap_sum += min_w
            details.append({
                "symbol": sym,
                "weight_fund_a": w_a,
                "weight_fund_b": w_b,
                "common_min_weight": min_w,
            })

        # Sort common symbols by highest combined weight
        details.sort(key=lambda x: x["common_min_weight"], reverse=True)
        return overlap_sum, details

    def analyze_overlap(
        self,
        fund_metadata: Dict[str, str],  # fund_id -> fund_name
        max_overlap_threshold: float = 50.0,
        portfolio_weights: Optional[Dict[str, float]] = None,  # fund_id -> allocation weight in portfolio (0 to 1)
    ) -> OverlapReport:
        """
        Full overlap and concentration risk analysis across a set of funds.
        """
        fund_ids = list(fund_metadata.keys())
        if len(fund_ids) < 2:
            return OverlapReport(
                pairwise_overlaps=[],
                common_consensus_symbols=[],
                concentration_alerts=[],
                recommended_pruned_funds=[]
            )

        positions = self.get_funds_holdings_raw(fund_ids)

        # Group positions by fund: fund_id -> {symbol: weight}
        fund_holdings: Dict[str, Dict[str, float]] = {fid: {} for fid in fund_ids}
        fund_industries: Dict[str, Dict[str, float]] = {fid: {} for fid in fund_ids}

        for p in positions:
            if p.fund_id in fund_holdings and p.symbol:
                fund_holdings[p.fund_id][p.symbol] = p.weight
                fund_industries[p.fund_id][p.industry] = (
                    fund_industries[p.fund_id].get(p.industry, 0.0) + p.weight
                )

        # Pairwise overlap comparisons
        pairwise_results: List[OverlapPairResult] = []
        redundant_funds: Set[str] = set()

        for i in range(len(fund_ids)):
            for j in range(i + 1, len(fund_ids)):
                id_a, id_b = fund_ids[i], fund_ids[j]
                name_a, name_b = fund_metadata[id_a], fund_metadata[id_b]
                overlap_val, common_details = self.calculate_pairwise_overlap(
                    fund_holdings[id_a], fund_holdings[id_b]
                )
                is_redundant = overlap_val >= max_overlap_threshold
                if is_redundant:
                    # Flag the second fund as potentially redundant
                    redundant_funds.add(id_b)

                pairwise_results.append(
                    OverlapPairResult(
                        fund_a_id=id_a,
                        fund_a_name=name_a,
                        fund_b_id=id_b,
                        fund_b_name=name_b,
                        overlap_pct=round(overlap_val, 2),
                        common_symbols_count=len(common_details),
                        top_common_symbols=common_details[:5],
                        is_redundant=is_redundant,
                    )
                )

        # Top consensus symbols across all inspected funds
        symbol_fund_counts: Dict[str, List[Tuple[str, float]]] = {}
        for fid, holdings in fund_holdings.items():
            for sym, w in holdings.items():
                if sym not in symbol_fund_counts:
                    symbol_fund_counts[sym] = []
                symbol_fund_counts[sym].append((fund_metadata[fid], w))

        consensus_symbols = []
        for sym, appearances in symbol_fund_counts.items():
            if len(appearances) >= 2:
                avg_w = sum(a[1] for a in appearances) / len(appearances)
                consensus_symbols.append({
                    "symbol": sym,
                    "funds_holding_count": len(appearances),
                    "funds": [a[0] for a in appearances],
                    "average_weight": round(avg_w, 2),
                })
        consensus_symbols.sort(
            key=lambda x: (x["funds_holding_count"], x["average_weight"]),
            reverse=True,
        )

        # Concentration risk alerts (if portfolio weights provided)
        alerts: List[PortfolioConcentrationAlert] = []
        if portfolio_weights:
            effective_stock_weights: Dict[str, float] = {}
            effective_industry_weights: Dict[str, float] = {}

            for fid, alloc_weight in portfolio_weights.items():
                holdings = fund_holdings.get(fid, {})
                for sym, w in holdings.items():
                    # w is percentage of fund (e.g. 15%), alloc_weight is fraction (e.g. 0.30)
                    effective_stock_weights[sym] = effective_stock_weights.get(sym, 0.0) + (w * alloc_weight)

                industries = fund_industries.get(fid, {})
                for ind, w in industries.items():
                    effective_industry_weights[ind] = effective_industry_weights.get(ind, 0.0) + (w * alloc_weight)

            # Check single-stock concentration
            for sym, eff_w in sorted(effective_stock_weights.items(), key=lambda x: x[1], reverse=True):
                if eff_w >= 15.0:
                    alerts.append(
                        PortfolioConcentrationAlert(
                            severity="HIGH",
                            asset=sym,
                            asset_type="STOCK",
                            effective_weight_pct=round(eff_w, 2),
                            message=f"ریسک تمرکز بسیار بالا روی نماد «{sym}» ({eff_w:.1f}٪ از کل سبد) ناشی از هم‌پوشانی صندوق‌ها.",
                        )
                    )
                elif eff_w >= 8.0:
                    alerts.append(
                        PortfolioConcentrationAlert(
                            severity="MEDIUM",
                            asset=sym,
                            asset_type="STOCK",
                            effective_weight_pct=round(eff_w, 2),
                            message=f"تمرکز نسبتاً بالا روی نماد «{sym}» ({eff_w:.1f}٪ از کل سبد).",
                        )
                    )

            # Check industry concentration
            for ind, eff_w in sorted(effective_industry_weights.items(), key=lambda x: x[1], reverse=True):
                if eff_w >= 30.0:
                    alerts.append(
                        PortfolioConcentrationAlert(
                            severity="HIGH",
                            asset=ind,
                            asset_type="INDUSTRY",
                            effective_weight_pct=round(eff_w, 2),
                            message=f"ریسک تمرکز سنگین روی صنعت «{ind}» ({eff_w:.1f}٪ از کل سبد).",
                        )
                    )

        return OverlapReport(
            pairwise_overlaps=pairwise_results,
            common_consensus_symbols=consensus_symbols[:10],
            concentration_alerts=alerts,
            recommended_pruned_funds=[fund_metadata[fid] for fid in redundant_funds],
        )


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")

    client = FundbaseOverlapClient()
    # Test with اهرم, شتاب, جهش
    test_funds = {
        "61ea4c20-f594-4ace-a589-2c0322cda0b3": "اهرم",
        "9456988f-2f9b-4243-ac5c-9cc0514c618f": "شتاب",
        "7c1e5cb2-9340-42cc-85ab-2da8f47d9dbc": "جهش",
    }
    # Simulated portfolio: 40% اهرم, 30% شتاب, 30% جهش
    simulated_weights = {
        "61ea4c20-f594-4ace-a589-2c0322cda0b3": 0.40,
        "9456988f-2f9b-4243-ac5c-9cc0514c618f": 0.30,
        "7c1e5cb2-9340-42cc-85ab-2da8f47d9dbc": 0.30,
    }

    report = client.analyze_overlap(
        fund_metadata=test_funds,
        max_overlap_threshold=45.0,
        portfolio_weights=simulated_weights
    )

    print("=== ماتریس هم‌پوشانی جفتی صندوق‌ها ===")
    for p in report.pairwise_overlaps:
        status = "⚠️ هم‌پوشانی بالا (تکراری)" if p.is_redundant else "🟢 هم‌پوشانی مجاز"
        print(f"{p.fund_a_name} ↔ {p.fund_b_name}: {p.overlap_pct}% ({p.common_symbols_count} نماد مشترک) | {status}")
        for cs in p.top_common_symbols[:3]:
            print(f"   • {cs['symbol']}: {cs['weight_fund_a']:.1f}% در {p.fund_a_name} | {cs['weight_fund_b']:.1f}% در {p.fund_b_name}")

    print("\n=== نمادهای مورد اجماع مدیران صندوق‌ها ===")
    for cs in report.common_consensus_symbols[:5]:
        print(f"نماد {cs['symbol']}: مشترک در {cs['funds_holding_count']} صندوق ({', '.join(cs['funds'])}) با میانگین وزن {cs['average_weight']}%")

    print("\n=== هشدارهای ریسک تمرکز سبد ===")
    for alert in report.concentration_alerts:
        print(f"[{alert.severity}] {alert.message}")
