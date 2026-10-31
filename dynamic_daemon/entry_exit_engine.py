"""
Logical Intraday Entry & 4-Pillar Exit Decision Engine.
Evaluates live TSETMC + Fundbase + FX Dirham Radar snapshots every 30 minutes:
  - Issues BUY_ENTRY or WAIT_FOR_DIP on recommended portfolio targets.
  - Monitors open positions (MANUAL_REAL & AUTO_VIRTUAL) against 4 Exit Pillars:
      1. خروج پول درشت (Heavy Smart-Money / Whale Distribution)
      2. تغییر رژیم کلان (Macro Regime Reversal)
      3. شکست حد ضرر متحرک (Dynamic Trailing Stop Breach)
      4. باد شدن حباب زنده (Live Synthetic Bubble Blowout)
"""

from dataclasses import dataclass, field
import os
import sys
from typing import Dict, List, Optional
import pandas as pd

# Link core quantitative analytics (bundled in PROJECT_ROOT/src or sibling iran_smart_money_engine)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_ENGINE_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "..", "iran_smart_money_engine"))
for _p in (PROJECT_ROOT, CORE_ENGINE_PATH):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from src.data.fund_tracker import FundTracker
from src.data.fundbase_gold import FundbaseGoldClient
from src.data.fundbase_leveraged import FundbaseLeveragedClient
from src.data.fundbase_fixed_income import FundbaseFixedIncomeClient
from src.data.fundbase_portfolio_search import FundbasePortfolioSearchClient, TopFundTradeItem
from src.data.fundbase_players import FundbasePlayersClient
from src.analytics.macro_flow import MacroFlowAnalyzer, MacroFlowReport
from src.analytics.sector_rotation import SectorRotationAnalyzer
from src.analytics.smart_money_screener import SmartMoneyScreener, SmartMoneyCandidate
from src.analytics.lagging_detector import ValuationLaggingDetector, ValuationLaggingReport
from src.analytics.fx_macro_radar import FXMacroRadar, FXMacroRadarSnapshot
from dynamic_daemon.jalali import to_shamsi_datetime
from src.analytics.asset_allocator import MultiRegimeAssetAllocator, DynamicAllocationPlan, MarketRegime

from dynamic_daemon.market_calendar import MarketSessionState, TehranMarketCalendar
from dynamic_daemon.position_store import HybridPositionStore, PositionRecord


STOCK_REFERENCE_PRICES: Dict[str, float] = {
    "فولاد": 4850.0,
    "شستا": 1280.0,
    "فملی": 6920.0,
    "ونوین": 3410.0,
    "وغدیر": 18300.0,
    "اروند": 11500.0,
    "سیسکو": 16400.0,
    "نوری": 218500.0,
    "بوعلی": 64200.0,
    "پارسان": 36100.0,
    "تاپیکو": 14200.0,
    "فارس": 9750.0,
    "وبملت": 2450.0,
    "شپنا": 4120.0,
    "شتران": 2890.0,
    "خودرو": 3150.0,
    "خساپا": 2640.0,
    "ثمر": 14616.0,
    "شکام": 15200.0,
    "وامیر": 14800.0,
    "کپشیر": 38500.0,
    "فنورد": 13230.0,
    "حفاری": 6020.0,
    "ودی": 6700.0,
}


@dataclass
class SignalDecision:
    symbol: str
    name: str
    asset_class: str
    action: str  # "BUY_ENTRY", "EXIT", "SWITCH", "HOLD", "WAIT"
    tracking_mode: str  # "MANUAL_REAL", "AUTO_VIRTUAL", "WATCHLIST"
    current_price: float
    entry_price: float = 0.0
    peak_price: float = 0.0
    trailing_stop_price: float = 0.0
    pnl_pct: float = 0.0
    live_bubble_pct: float = 0.0
    buyer_power: float = 1.0
    net_inflow_b_toman: float = 0.0
    suggested_weight_pct: float = 0.0
    trigger_pillar: str = ""
    reason: str = ""


@dataclass
class IntradayCycleReport:
    timestamp: str
    session: MarketSessionState
    regime: MarketRegime
    regime_changed: bool
    previous_regime: str
    dirham_spread_pct: float
    spot_usd_rials: float
    implied_usd_rials: float
    allocation_plan: DynamicAllocationPlan
    decisions: List[SignalDecision] = field(default_factory=list)

    @property
    def urgent_signals(self) -> List[SignalDecision]:
        return [d for d in self.decisions if d.action in ("BUY_ENTRY", "EXIT", "SWITCH")]


class IntradayEntryExitEngine:
    """
    Stateful intraday decision engine combining Phase 1-3 analytics with position lifecycle management.
    """

    RIALS_TO_BILLION_TOMAN = 1e10

    # Thresholds for the 4 Exit Pillars
    GOLD_BUBBLE_EXIT_PCT = 5.0
    LEVERAGED_BUBBLE_EXIT_PCT = 6.0
    WHALE_EXIT_BUYER_POWER = 0.65
    WHALE_EXIT_NET_OUTFLOW_B_TOMAN = -10.0
    BEARISH_DIRHAM_SPREAD_EXIT_PCT = -0.80

    # Entry thresholds
    GOLD_MAX_ENTRY_BUBBLE_PCT = 1.5
    LEVERAGED_MAX_ENTRY_BUBBLE_PCT = 2.0
    MIN_ETF_LIQUIDITY_B_TOMAN = 10.0

    def __init__(
        self,
        store: HybridPositionStore,
        total_capital_toman: float = 10_000_000.0,
        top_n_stocks: int = 5
    ):
        self.store = store
        self.total_capital_toman = total_capital_toman
        self.top_n_stocks = max(1, top_n_stocks)
        self.macro_analyzer = MacroFlowAnalyzer()
        self.sector_analyzer = SectorRotationAnalyzer()
        self.val_detector = ValuationLaggingDetector(min_trade_value_b_toman=self.MIN_ETF_LIQUIDITY_B_TOMAN)
        self.screener = SmartMoneyScreener()
        self.allocator = MultiRegimeAssetAllocator()

    def _fetch_institutional_and_whale_intel(self, enabled: bool):
        inst_buys: Dict[str, TopFundTradeItem] = {}
        inst_sells: Dict[str, TopFundTradeItem] = {}
        whale_net_b_toman: Dict[str, float] = {}
        whale_aliases: Dict[str, str] = {}
        whale_recent_txs: List[Dict[str, Any]] = []
        if not enabled:
            return inst_buys, inst_sells, whale_net_b_toman, whale_aliases, whale_recent_txs

        try:
            ps_client = FundbasePortfolioSearchClient()
            for b in ps_client.get_top_fund_buys(months=3, level="symbol", direction="buy", limit=60):
                if b.name:
                    inst_buys[b.name] = b
            for s in ps_client.get_top_fund_buys(months=3, level="symbol", direction="sell", limit=40):
                if s.name:
                    inst_sells[s.name] = s
        except Exception:
            pass

        try:
            pl_client = FundbasePlayersClient()
            for tx in pl_client.get_latest_transactions(limit=150):
                sym = tx.symbol.strip()
                if not sym:
                    continue
                signed_val = tx.value_billion_toman if tx.is_buy else -abs(tx.value_billion_toman)
                whale_net_b_toman[sym] = whale_net_b_toman.get(sym, 0.0) + signed_val
                if sym not in whale_aliases and abs(signed_val) >= 1.0:
                    whale_aliases[sym] = tx.alias

                price = round(abs(tx.value_rial / tx.shares_change), 0) if tx.shares_change else 0.0
                whale_recent_txs.append({
                    "symbol": sym,
                    "alias": tx.alias,
                    "date": tx.date,
                    "is_buy": tx.is_buy,
                    "price_rial": price,
                    "value_billion_toman": abs(tx.value_billion_toman),
                })
        except Exception:
            pass

        return inst_buys, inst_sells, whale_net_b_toman, whale_aliases, whale_recent_txs

    def evaluate_cycle(
        self,
        df: pd.DataFrame,
        fx_snap: Optional[FXMacroRadarSnapshot] = None,
        session: Optional[MarketSessionState] = None,
        enrich_fundbase: bool = True
    ) -> IntradayCycleReport:
        """
        Runs one full 30-minute intraday analysis cycle:
          1. Computes Macro Flow, Synthetic NAV, Catch-Up Spreads, FX Parity & Active Regime.
          2. Evaluates all open positions against the 4 Exit Pillars.
          3. Evaluates recommended portfolio targets for logical BUY_ENTRY vs WAIT.
        """
        if session is None:
            session = TehranMarketCalendar.get_session_state(force_open=True)

        tagged_df = FundTracker.tag_dataframe(df)
        macro_report = self.macro_analyzer.analyze(tagged_df)
        sector_summaries = self.sector_analyzer.analyze(tagged_df)

        fb_lev_map = None
        if enrich_fundbase:
            try:
                fb_lev_map = FundbaseLeveragedClient().get_latest_leveraged_metrics()
            except Exception:
                fb_lev_map = None

        val_report = self.val_detector.analyze(tagged_df, live_leverage_map=fb_lev_map)

        if enrich_fundbase and val_report.gold_valuations:
            try:
                fb_gold = FundbaseGoldClient().get_latest_gold_metrics()
                if fb_gold:
                    self.val_detector.gold_engine.enrich_with_fundbase(val_report.gold_valuations, fb_gold)
                    val_report.best_gold_fund = self.val_detector.gold_engine.pick_best_gold_fund(
                        val_report.gold_valuations
                    )
            except Exception:
                pass

        best_fi_sym, best_fi_name = "افران", "صندوق درآمد ثابت افران"
        if enrich_fundbase:
            try:
                reserves = FundbaseFixedIncomeClient().get_latest_reserves(limit=50)
                if reserves:
                    top_fi = max(reserves.values(), key=lambda r: r.zakhireh)
                    best_fi_sym = top_fi.symbol
                    best_fi_name = f"صندوق درآمد ثابت {top_fi.symbol}"
            except Exception:
                pass

        top_sectors = [s.sector_name for s in sector_summaries if s.net_real_inflow_b_toman > 0][:5]
        candidates = self.screener.screen(tagged_df, top_sectors=top_sectors)
        inst_buys, inst_sells, whale_net_map, whale_aliases = self._fetch_institutional_and_whale_intel(enrich_fundbase)

        dirham_spread = fx_snap.dirham_arbitrage_spread_pct if fx_snap else 0.0
        spot_usd = fx_snap.spot_usd_rials if fx_snap else 0.0
        implied_usd = fx_snap.implied_usd_from_aed if fx_snap else 0.0

        eq_sum = macro_report.asset_summaries.get("سهام و حق تقدم")
        lev_sum = macro_report.asset_summaries.get("صندوق اهرمی")
        gold_sum = macro_report.asset_summaries.get("صندوق طلا")

        eq_inflow = (eq_sum.net_real_inflow_b_toman if eq_sum else 0.0) + (
            lev_sum.net_real_inflow_b_toman if lev_sum else 0.0
        )
        eq_power = eq_sum.avg_buyer_power if eq_sum else 1.0
        gold_inflow = gold_sum.net_real_inflow_b_toman if gold_sum else 0.0

        best_gold_sym = val_report.best_gold_fund.symbol if val_report.best_gold_fund else "عیار"
        best_gold_nm = val_report.best_gold_fund.name if val_report.best_gold_fund else "صندوق طلای عیار مفید"
        top_lev_obj = val_report.top_catch_up_leveraged or val_report.leveraged_leader
        top_lev_sym = top_lev_obj.symbol if top_lev_obj else "شتاب"
        top_lev_nm = top_lev_obj.name if top_lev_obj else "صندوق شتاب مفید"
        top_stock_sym = candidates[0].symbol if candidates else "فولاد"
        top_stock_nm = candidates[0].name if candidates else "فولاد مبارکه اصفهان"

        alloc_plan = self.allocator.generate_plan(
            equity_net_inflow_b_toman=eq_inflow,
            buyer_power_ratio=eq_power,
            dirham_spread_pct=dirham_spread,
            best_gold_symbol=best_gold_sym,
            best_gold_name=best_gold_nm,
            catch_up_leveraged_symbol=top_lev_sym,
            catch_up_leveraged_name=top_lev_nm,
            best_fixed_income_symbol=best_fi_sym,
            best_fixed_income_name=best_fi_name,
            top_stock_symbol=top_stock_sym,
            top_stock_name=top_stock_nm,
            gold_flow_b_toman=gold_inflow
        )

        prev_regime = self.store.last_regime
        curr_regime_str = alloc_plan.regime.value
        regime_changed = bool(prev_regime and prev_regime != curr_regime_str)
        self.store.last_regime = curr_regime_str
        self.store.save()

        # Index quick lookups by symbol
        gold_map = {g.symbol: g for g in val_report.gold_valuations}
        lev_map = {l.symbol: l for l in val_report.leveraged_analyses}
        cand_map = {c.symbol: c for c in candidates}
        row_map = {str(r.get("symbol", "")).strip(): r for _, r in tagged_df.iterrows()}

        decisions: List[SignalDecision] = []

        # ------------------------------------------------------------------
        # STEP 1: Evaluate all existing open positions (4 Exit Pillars)
        # ------------------------------------------------------------------
        open_symbols = list(self.store.positions.keys())
        for sym in open_symbols:
            pos = self.store.positions.get(sym)
            if not pos:
                continue
            decision = self._evaluate_open_position(
                pos=pos,
                row=row_map.get(sym),
                gold_val=gold_map.get(sym),
                lev_val=lev_map.get(sym),
                all_gold_vals=val_report.gold_valuations,
                regime=alloc_plan.regime,
                dirham_spread=dirham_spread,
                session=session
            )
            decisions.append(decision)

        # ------------------------------------------------------------------
        # STEP 2: Evaluate recommended portfolio slices for BUY_ENTRY vs WAIT
        # ------------------------------------------------------------------
        held_now = set(self.store.positions.keys()) | {d.symbol for d in decisions}
        for alloc in alloc_plan.allocations:
            sym = alloc.recommended_symbol
            if not sym or sym == "—" or alloc.target_weight_pct <= 0:
                continue
            if "درآمد ثابت" in alloc.asset_class:
                continue

            if "سهام" in alloc.asset_class:
                stock_decs = self._evaluate_top_stocks(
                    equity_budget_weight_pct=alloc.target_weight_pct,
                    candidates=candidates,
                    row_map=row_map,
                    inst_buys=inst_buys,
                    inst_sells=inst_sells,
                    whale_net_map=whale_net_map,
                    whale_aliases=whale_aliases,
                    held_now=held_now,
                    regime=alloc_plan.regime,
                    session=session
                )
                for sd in stock_decs:
                    decisions.append(sd)
                    held_now.add(sd.symbol)
                continue

            if sym in held_now:
                continue

            entry_dec = self._evaluate_entry_candidate(
                symbol=sym,
                fallback_name=alloc.recommended_name,
                alloc_class=alloc.asset_class,
                target_weight_pct=alloc.target_weight_pct,
                row=row_map.get(sym),
                gold_val=gold_map.get(sym),
                lev_val=lev_map.get(sym),
                stock_cand=cand_map.get(sym),
                regime=alloc_plan.regime,
                dirham_spread=dirham_spread,
                session=session
            )
            if entry_dec:
                decisions.append(entry_dec)
                held_now.add(sym)

        return IntradayCycleReport(
            timestamp=to_shamsi_datetime(session.now_tehran, full_words=True),
            session=session,
            regime=alloc_plan.regime,
            regime_changed=regime_changed,
            previous_regime=prev_regime,
            dirham_spread_pct=dirham_spread,
            spot_usd_rials=spot_usd,
            implied_usd_rials=implied_usd,
            allocation_plan=alloc_plan,
            decisions=decisions
        )

    def _extract_live_metrics(self, sym: str, row, gold_val, lev_val):
        """Extracts unified live price, bubble %, buyer power, and net inflow."""
        if gold_val is not None:
            return (
                gold_val.last_price,
                gold_val.synthetic_bubble_pct,
                gold_val.buyer_power_ratio,
                gold_val.net_real_inflow_b_toman
            )
        if lev_val is not None:
            return (
                lev_val.last_price,
                lev_val.p_nav_bubble_pct,
                lev_val.buyer_power_ratio,
                lev_val.net_real_inflow_b_toman
            )
        if row is not None:
            last_p = float(row.get("last_price", 0.0) or row.get("close_price", 0.0))
            close_p = float(row.get("close_price", last_p) or last_p)
            buy_v = float(row.get("buy_vol_real", 0.0))
            sell_v = float(row.get("sell_vol_real", 0.0))
            buy_c = float(row.get("buy_count_real", 0.0))
            sell_c = float(row.get("sell_count_real", 0.0))
            inflow = ((buy_v - sell_v) * close_p) / self.RIALS_TO_BILLION_TOMAN
            b_pc = (buy_v * close_p / buy_c) if buy_c > 0 else 0.0
            s_pc = (sell_v * close_p / sell_c) if sell_c > 0 else 0.0
            power = (b_pc / s_pc) if s_pc > 0 else 1.0
            nav = float(row.get("nav", 0.0) or 0.0)
            bubble = (((last_p - nav) / nav) * 100.0) if nav > 0 else 0.0
            return last_p, round(bubble, 2), round(power, 2), round(inflow, 2)
        return 0.0, 0.0, 1.0, 0.0

    def _evaluate_open_position(
        self,
        pos: PositionRecord,
        row,
        gold_val,
        lev_val,
        all_gold_vals,
        regime: MarketRegime,
        dirham_spread: float,
        session: MarketSessionState
    ) -> SignalDecision:
        """
        Checks the 4 explicit Exit Pillars for an active position:
          1. خروج پول درشت (Whale Outflow)
          2. تغییر رژیم کلان (Macro Regime Reversal)
          3. شکست حد ضرر متحرک (Dynamic Trailing Stop Breach)
          4. باد شدن حباب زنده (Live Synthetic Bubble Blowout)
        """
        last_price, live_bubble, buyer_power, net_inflow = self._extract_live_metrics(
            pos.symbol, row, gold_val, lev_val
        )
        if last_price <= 0:
            last_price = pos.peak_price

        # Update peak price BEFORE checking trailing stop
        self.store.update_market_price(pos.symbol, last_price)
        trail_stop = pos.compute_trailing_stop()
        pnl = pos.current_pnl_pct(last_price)

        is_tradable_now = TehranMarketCalendar.is_asset_tradable(pos.asset_class, session)
        if not is_tradable_now:
            return SignalDecision(
                symbol=pos.symbol,
                name=pos.name,
                asset_class=pos.asset_class,
                action="HOLD",
                tracking_mode=pos.tracking_mode,
                current_price=last_price,
                entry_price=pos.entry_price,
                peak_price=pos.peak_price,
                trailing_stop_price=trail_stop,
                pnl_pct=pnl,
                live_bubble_pct=live_bubble,
                buyer_power=buyer_power,
                net_inflow_b_toman=net_inflow,
                reason=f"بازار این نماد در حال حاضر بسته است ({session.session_label})؛ نگهداری تا بازگشایش."
            )

        exit_pillar = ""
        exit_reason = ""
        action_type = "EXIT"

        # PILLAR 1: خروج پول درشت (Whale / Smart Money Distribution)
        if buyer_power <= self.WHALE_EXIT_BUYER_POWER and net_inflow <= self.WHALE_EXIT_NET_OUTFLOW_B_TOMAN:
            exit_pillar = "۱. خروج پول درشت"
            exit_reason = (
                f"توزیع سنگین پول هوشمند به حقیقی خرد (قدرت خریدار {buyer_power:.2f} و خالص خروج {net_inflow:+.1f} همت)؛ "
                "سیگنال خروج فوری جهت حفظ سرمایه."
            )

        # PILLAR 2: تغییر رژیم کلان (Macro Regime Shift)
        elif "اهرمی" in pos.asset_class and regime == MarketRegime.BEAR_CRASH:
            exit_pillar = "۲. تغییر رژیم کلان"
            exit_reason = "ورود بازار به رژیم رکود و نزول بورس (Bear Market)؛ نگهداری صندوق اهرمی اکیداً ممنوع — خروج کامل."
        elif "سهام" in pos.asset_class and regime == MarketRegime.BEAR_CRASH and buyer_power < 0.90:
            exit_pillar = "۲. تغییر رژیم کلان"
            exit_reason = "تغییر رژیم کلان به رکود همراه با ضعف تقاضا؛ خروج و پارک در صندوق درآمد ثابت."
        elif "طلا" in pos.asset_class and dirham_spread <= self.BEARISH_DIRHAM_SPREAD_EXIT_PCT and buyer_power < 0.95:
            exit_pillar = "۲. تغییر رژیم کلان (ارزی)"
            exit_reason = (
                f"واگرایی منفی شدید حواله درهم دبی نسبت به دلار تهران ({dirham_spread:+.2f}%) همراه با افت قدرت خریدار ({buyer_power:.2f})؛ "
                "سیگنال اصلاح نرخ ارز و خروج از طلا."
            )

        # PILLAR 3: شکست حد ضرر متحرک (Trailing Stop Breach)
        elif trail_stop > 0 and last_price <= trail_stop:
            exit_pillar = "۳. شکست حد ضرر متحرک"
            exit_reason = (
                f"قیمت لحظه‌ای ({last_price:,.0f}) به زیر حد ضرر متحرک ({trail_stop:,.0f} ریال، محاسبه‌شده از سقف {pos.peak_price:,.0f}) نفوذ کرد؛ "
                f"خروج منضبط با بازده {pnl:+.2f}%."
            )

        # PILLAR 4: باد شدن حباب زنده (Live Bubble Blowout)
        elif "طلا" in pos.asset_class and live_bubble >= self.GOLD_BUBBLE_EXIT_PCT:
            exit_pillar = "۴. باد شدن حباب زنده"
            cheaper = [
                g for g in (all_gold_vals or [])
                if g.is_liquid and g.symbol != pos.symbol and g.synthetic_bubble_pct <= 1.0
            ]
            if cheaper:
                action_type = "SWITCH"
                alt = cheaper[0]
                exit_reason = (
                    f"حباب زنده {pos.symbol} به {live_bubble:+.1f}% رسید (اشباع حباب)! "
                    f"پیشنهاد فروش حباب و سوییچ آربیتراژی به «{alt.symbol}» (با حباب {alt.synthetic_bubble_pct:+.1f}%)."
                )
            else:
                exit_reason = (
                    f"حباب زنده {pos.symbol} به {live_bubble:+.1f}% متورم شد؛ "
                    "شناسایی سود و پارک موقت در درآمد ثابت تا تخلیه حباب."
                )
        elif "اهرمی" in pos.asset_class and live_bubble >= self.LEVERAGED_BUBBLE_EXIT_PCT and buyer_power < 1.10:
            exit_pillar = "۴. باد شدن حباب زنده"
            exit_reason = (
                f"تورم بیش از حد حباب قیمتی ({live_bubble:+.1f}%) همراه با کاهش قدرت خریدار ({buyer_power:.2f})؛ خروج و شناسایی سود."
            )

        if exit_pillar:
            self.store.handle_exit_signal(pos.symbol, last_price, f"{exit_pillar}: {exit_reason}")
            return SignalDecision(
                symbol=pos.symbol,
                name=pos.name,
                asset_class=pos.asset_class,
                action=action_type,
                tracking_mode=pos.tracking_mode,
                current_price=last_price,
                entry_price=pos.entry_price,
                peak_price=pos.peak_price,
                trailing_stop_price=trail_stop,
                pnl_pct=pnl,
                live_bubble_pct=live_bubble,
                buyer_power=buyer_power,
                net_inflow_b_toman=net_inflow,
                trigger_pillar=exit_pillar,
                reason=exit_reason
            )

        return SignalDecision(
            symbol=pos.symbol,
            name=pos.name,
            asset_class=pos.asset_class,
            action="HOLD",
            tracking_mode=pos.tracking_mode,
            current_price=last_price,
            entry_price=pos.entry_price,
            peak_price=pos.peak_price,
            trailing_stop_price=trail_stop,
            pnl_pct=pnl,
            live_bubble_pct=live_bubble,
            buyer_power=buyer_power,
            net_inflow_b_toman=net_inflow,
            reason=(
                f"روند سالم (بازده فعلی {pnl:+.2f}% | سقف تجربه شده {pos.peak_price:,.0f} | "
                f"حد ضرر متحرک فعال: {trail_stop:,.0f} ریال | حباب زنده: {live_bubble:+.1f}%)."
            )
        )

    def _evaluate_entry_candidate(
        self,
        symbol: str,
        fallback_name: str,
        alloc_class: str,
        target_weight_pct: float,
        row,
        gold_val,
        lev_val,
        stock_cand: Optional[SmartMoneyCandidate],
        regime: MarketRegime,
        dirham_spread: float,
        session: MarketSessionState
    ) -> Optional[SignalDecision]:
        """
        Determines whether a target portfolio asset has an optimal BUY_ENTRY setup right now or should WAIT.
        """
        if "طلا" in alloc_class:
            internal_class = "صندوق طلا"
        elif "اهرمی" in alloc_class:
            internal_class = "صندوق اهرمی"
        else:
            internal_class = "سهام و حق تقدم"

        last_price, live_bubble, buyer_power, net_inflow = self._extract_live_metrics(
            symbol, row, gold_val, lev_val
        )
        if last_price <= 0:
            return None

        if not TehranMarketCalendar.is_asset_tradable(internal_class, session):
            return SignalDecision(
                symbol=symbol,
                name=fallback_name,
                asset_class=internal_class,
                action="WAIT",
                tracking_mode="WATCHLIST",
                current_price=last_price,
                live_bubble_pct=live_bubble,
                buyer_power=buyer_power,
                net_inflow_b_toman=net_inflow,
                suggested_weight_pct=target_weight_pct,
                reason=f"در لیست خرید ({target_weight_pct:.0f}% سبد)، اما تایم معاملاتی نماد فعلاً بسته است."
            )

        alloc_toman = round(self.total_capital_toman * (target_weight_pct / 100.0), 0)

        # 1. GOLD ETF ENTRY LOGIC (e.g., عیار)
        if internal_class == "صندوق طلا":
            if gold_val and not gold_val.is_liquid:
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                    live_bubble_pct=live_bubble, buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                    suggested_weight_pct=target_weight_pct,
                    reason="رد صلاحیت به دلیل نقدشوندگی زیر ۱۰ همت (پرهیز از تله نقدشوندگی)."
                )
            if live_bubble > self.GOLD_MAX_ENTRY_BUBBLE_PCT:
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                    live_bubble_pct=live_bubble, buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                    suggested_weight_pct=target_weight_pct,
                    reason=f"صبر کنید: حباب لحظه‌ای ({live_bubble:+.1f}%) بالاتر از سقف مجاز ورود (+۱.۵٪) است؛ منتظر تعدیل حباب بمانید."
                )
            if dirham_spread <= -0.50 and buyer_power < 1.0:
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                    live_bubble_pct=live_bubble, buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                    suggested_weight_pct=target_weight_pct,
                    reason=f"صبر کنید: درهم دبی پایین‌تر از دلار تهران است ({dirham_spread:+.2f}%)؛ احتمال افت کوتاه‌مدت و خرید ارزان‌تر."
                )
            if buyer_power >= 1.05 or live_bubble <= -0.5 or dirham_spread >= 0.4:
                pos = self.store.open_virtual_position(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    entry_price=last_price, entry_regime=regime.value,
                    entry_bubble_pct=live_bubble, allocated_toman=alloc_toman
                )
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="BUY_ENTRY", tracking_mode=pos.tracking_mode,
                    current_price=last_price, entry_price=last_price, peak_price=last_price,
                    trailing_stop_price=pos.compute_trailing_stop(),
                    live_bubble_pct=live_bubble, buyer_power=buyer_power,
                    net_inflow_b_toman=net_inflow, suggested_weight_pct=target_weight_pct,
                    trigger_pillar="نقطه ورود بهینه طلا",
                    reason=(
                        f"نقدشوندگی بالا + حباب زنده جذاب ({live_bubble:+.1f}%) + تایید برابری درهم ({dirham_spread:+.2f}%) "
                        f"و قدرت خریدار ({buyer_power:.2f}). ورود با وزن {target_weight_pct:.0f}% ({alloc_toman:,.0f} تومان)."
                    )
                )

        # 2. LEVERAGED ETF ENTRY LOGIC (e.g., شتاب / اهرم)
        elif internal_class == "صندوق اهرمی":
            if regime == MarketRegime.BEAR_CRASH:
                return None
            if lev_val and not lev_val.is_liquid:
                return None
            if lev_val and lev_val.is_queue_locked:
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                    live_bubble_pct=live_bubble, buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                    suggested_weight_pct=target_weight_pct,
                    reason="قفل در صف خرید سقف روزانه؛ از ثبت سفارش سرخطی هیجانی پرهیز کنید یا صندوق هم‌گروه عقب‌افتاده را بررسی کنید."
                )
            if live_bubble > self.LEVERAGED_MAX_ENTRY_BUBBLE_PCT:
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                    live_bubble_pct=live_bubble, buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                    suggested_weight_pct=target_weight_pct,
                    reason=f"صبر کنید: حباب صندوق اهرمی ({live_bubble:+.1f}%) بالاست؛ منتظر پولبک به محدوده NAV بمانید."
                )
            catchup_ok = bool(lev_val and lev_val.adjusted_spread_vs_leader >= 0.8 and buyer_power >= 1.05)
            momentum_ok = buyer_power >= 1.20 and net_inflow > 0
            if catchup_ok or momentum_ok:
                pos = self.store.open_virtual_position(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    entry_price=last_price, entry_regime=regime.value,
                    entry_bubble_pct=live_bubble, allocated_toman=alloc_toman
                )
                spread_note = f"، اسپرد جاماندگی از لیدر: +{lev_val.adjusted_spread_vs_leader:.2f}%" if lev_val else ""
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="BUY_ENTRY", tracking_mode=pos.tracking_mode,
                    current_price=last_price, entry_price=last_price, peak_price=last_price,
                    trailing_stop_price=pos.compute_trailing_stop(),
                    live_bubble_pct=live_bubble, buyer_power=buyer_power,
                    net_inflow_b_toman=net_inflow, suggested_weight_pct=target_weight_pct,
                    trigger_pillar="نقطه ورود اهرمی (جاماندگی / پول هوشمند)",
                    reason=(
                        f"قدرت خریدار {buyer_power:.2f}، ورود پول {net_inflow:+.1f} همت، حباب {live_bubble:+.1f}%{spread_note}. "
                        f"ورود با وزن {target_weight_pct:.0f}% ({alloc_toman:,.0f} تومان)."
                    )
                )

        # 3. HIGH-CONVICTION STOCK ENTRY LOGIC (e.g., نوری / فولاد)
        else:
            pct_last = float(row.get("pct_change_last", 0.0)) if row is not None else 0.0
            if pct_last >= 4.7:
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                    buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                    suggested_weight_pct=target_weight_pct,
                    reason=f"نزدیک/قفل سقف روزانه ({pct_last:+.1f}%)؛ صبر برای متعادل شدن تابلو."
                )
            score = stock_cand.smart_money_score if stock_cand else 0.0
            if score >= 65.0 or (buyer_power >= 1.35 and net_inflow > 0):
                pos = self.store.open_virtual_position(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    entry_price=last_price, entry_regime=regime.value,
                    allocated_toman=alloc_toman
                )
                return SignalDecision(
                    symbol=symbol, name=fallback_name, asset_class=internal_class,
                    action="BUY_ENTRY", tracking_mode=pos.tracking_mode,
                    current_price=last_price, entry_price=last_price, peak_price=last_price,
                    trailing_stop_price=pos.compute_trailing_stop(),
                    buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                    suggested_weight_pct=target_weight_pct,
                    trigger_pillar="ورود پول هوشمند تک‌سهم",
                    reason=(
                        f"امتیاز پول هوشمند بالا (قدرت خریدار {buyer_power:.2f} و ورود خالص {net_inflow:+.1f} همت). "
                        f"ورود با وزن {target_weight_pct:.0f}% ({alloc_toman:,.0f} تومان)."
                    )
                )

        return SignalDecision(
            symbol=symbol, name=fallback_name, asset_class=internal_class,
            action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
            live_bubble_pct=live_bubble, buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
            suggested_weight_pct=target_weight_pct,
            reason=f"تحت رصد در لیست سبد؛ منتظر تقویت قدرت خریدار (فعلی: {buyer_power:.2f}) برای صدور سیگنال ورود قطعی."
        )

    def _evaluate_top_stocks(
        self,
        equity_budget_weight_pct: float,
        candidates: List[SmartMoneyCandidate],
        row_map: Dict[str, any],
        inst_buys: Dict[str, TopFundTradeItem],
        inst_sells: Dict[str, TopFundTradeItem],
        whale_net_map: Dict[str, float],
        whale_aliases: Dict[str, str],
        held_now: set,
        regime: MarketRegime,
        session: MarketSessionState
    ) -> List[SignalDecision]:
        """
        Evaluates up to `self.top_n_stocks` (default 5) individual stocks simultaneously by fusing:
          1. Intraday Smart-Money Flow (buyer_power, net_inflow, smart_money_score)
          2. Institutional Mutual Fund Accumulation / Distribution (`get_top_fund_buys`)
          3. Top-500 Tracked Whale Buys / Sells (`get_tracked_investor_feed`)
        Automatically bypasses ceiling-locked stocks (+5% queue) to allocate across unlocked winners.
        """
        if regime == MarketRegime.BEAR_CRASH or equity_budget_weight_pct <= 0:
            return []

        internal_class = "سهام و حق تقدم"
        cand_by_sym = {c.symbol.strip(): c for c in candidates}

        # Gather all live stock symbols present in the snapshot
        live_stock_syms = [
            sym for sym, r in row_map.items()
            if str(r.get("asset_class", "")) == internal_class and sym not in held_now
        ]

        # OFF-HOURS / CLOUD FAILOVER: TSETMC stock feed is closed -> surface Top 5 Institutional + Whale Watchlist
        if not live_stock_syms:
            bond_prefixes = ("اراد", "اخزا", "تسه", "گام", "صکوك", "مرابحه", "اجاره")
            watchlist_pool = []
            all_intel_syms = set(inst_buys.keys()) | {s for s, v in whale_net_map.items() if v >= 10.0}
            for sym in all_intel_syms:
                # Exclude ETFs already present in row_map, treasury bonds, held symbols, or distributed stocks
                if sym in row_map or sym.startswith(bond_prefixes):
                    continue
                if FundTracker.classify_fund_type(sym) != internal_class:
                    continue
                if sym in held_now or sym in inst_sells or whale_net_map.get(sym, 0.0) <= -3.0:
                    continue
                ib = inst_buys.get(sym)
                wn = whale_net_map.get(sym, 0.0)
                inst_val = ib.net_value_billion_toman if ib else 0.0
                buyers = ib.buyer_count if ib else 0
                # Enforce liquidity & institutional depth guardrail (blocks thin small-caps like آکو)
                if inst_val < 50.0 and wn < 10.0:
                    continue
                rank_score = (inst_val / 80.0) + (buyers * 0.5) + min(25.0, wn * 0.4)
                watchlist_pool.append((rank_score, sym, ib, wn))

            watchlist_pool.sort(key=lambda x: x[0], reverse=True)
            out: List[SignalDecision] = []
            for _, sym, ib, wn in watchlist_pool[:self.top_n_stocks]:
                notes = []
                if ib:
                    notes.append(
                        f"انباشت صندوق‌ها: {ib.net_value_billion_toman:+,.0f} م.ت ({ib.buyer_count} صندوق خریدار، تغییر وزن {ib.weight_change:+.2f}%)"
                    )
                if wn > 0:
                    alias_str = f" توسط «{whale_aliases[sym]}»" if sym in whale_aliases else ""
                    notes.append(f"خرید نهنگ{alias_str}: {wn:+.1f} م.ت")
                out.append(
                    SignalDecision(
                        symbol=sym,
                        name=sym,
                        asset_class=internal_class,
                        action="WAIT",
                        tracking_mode="WATCHLIST",
                        current_price=0.0,
                        buyer_power=1.0,
                        net_inflow_b_toman=round(wn, 2),
                        suggested_weight_pct=round(equity_budget_weight_pct / self.top_n_stocks, 1),
                        reason="واچ‌لیست بازگشایش بازار سهام | " + " + ".join(notes)
                    )
                )
            return out

        # LIVE STOCK MARKET MODE: Rank all live stock candidates by fused 3-layer conviction score
        scored_stocks = []
        pool_syms = set(cand_by_sym.keys()) & set(live_stock_syms)
        # Also include live stocks with strong institutional/whale backing even if below screener cutoff
        for sym in live_stock_syms:
            if sym in inst_buys and inst_buys[sym].net_value_billion_toman >= 250.0:
                pool_syms.add(sym)
            elif whale_net_map.get(sym, 0.0) >= 5.0:
                pool_syms.add(sym)

        for sym in pool_syms:
            row = row_map.get(sym)
            if row is None:
                continue
            cand = cand_by_sym.get(sym)
            base_score = cand.smart_money_score if cand else 45.0
            ib = inst_buys.get(sym)
            isel = inst_sells.get(sym)
            wn = whale_net_map.get(sym, 0.0)

            inst_bonus = min(18.0, (ib.net_value_billion_toman / 150.0) + (ib.buyer_count * 0.2)) if ib else 0.0
            inst_penalty = 30.0 if (isel and abs(isel.net_value_billion_toman) >= 250.0) else 0.0
            whale_bonus = min(15.0, wn * 1.2) if wn > 0 else 0.0
            whale_penalty = 25.0 if wn <= -3.0 else 0.0

            composite = base_score + inst_bonus + whale_bonus - inst_penalty - whale_penalty
            scored_stocks.append((composite, sym, row, cand, ib, isel, wn))

        scored_stocks.sort(key=lambda x: x[0], reverse=True)
        top_slice = scored_stocks[:self.top_n_stocks]
        if not top_slice:
            return []

        tradable_now = TehranMarketCalendar.is_asset_tradable(internal_class, session)

        # Pre-check how many of Top N qualify for unlocked BUY_ENTRY so budget splits cleanly
        qualifying_syms = set()
        if tradable_now:
            for composite, sym, row, cand, ib, isel, wn in top_slice:
                last_price, _, buyer_power, net_inflow = self._extract_live_metrics(sym, row, None, None)
                pct_last = float(row.get("pct_change_last", 0.0) or 0.0)
                trade_val_b = float(row.get("value", 0.0) or 0.0) / self.RIALS_TO_BILLION_TOMAN
                if last_price <= 0 or pct_last >= 4.7 or trade_val_b < 5.0:
                    continue
                if (isel and abs(isel.net_value_billion_toman) >= 250.0) or wn <= -3.0:
                    continue
                if composite >= 65.0 or (buyer_power >= 1.35 and net_inflow > 0):
                    qualifying_syms.add(sym)

        per_entry_weight = round(equity_budget_weight_pct / max(1, len(qualifying_syms)), 1)

        decisions_out: List[SignalDecision] = []
        for composite, sym, row, cand, ib, isel, wn in top_slice:
            name = str(row.get("name", sym))
            last_price, _, buyer_power, net_inflow = self._extract_live_metrics(sym, row, None, None)
            pct_last = float(row.get("pct_change_last", 0.0) or 0.0)

            extra_tags = []
            if ib:
                extra_tags.append(f"انباشت صندوق‌ها {ib.net_value_billion_toman:+,.0f} م.ت ({ib.buyer_count} صندوق)")
            if wn >= 1.0:
                extra_tags.append(f"خرید نهنگ {wn:+.1f} م.ت")
            extra_str = (" | " + " + ".join(extra_tags)) if extra_tags else ""

            if not tradable_now:
                decisions_out.append(
                    SignalDecision(
                        symbol=sym, name=name, asset_class=internal_class,
                        action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                        buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                        suggested_weight_pct=round(equity_budget_weight_pct / len(top_slice), 1),
                        reason=f"در لیست ۵ سهم برتر، اما تایم معاملاتی بازار سهام بسته است{extra_str}."
                    )
                )
                continue

            if isel and abs(isel.net_value_billion_toman) >= 250.0:
                decisions_out.append(
                    SignalDecision(
                        symbol=sym, name=name, asset_class=internal_class,
                        action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                        buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                        reason=f"هشدار عرضه حقوقی/صندوق‌ها ({isel.net_value_billion_toman:,.0f} م.ت در ۳ ماه اخیر)؛ توقف ورود."
                    )
                )
                continue

            if wn <= -3.0:
                decisions_out.append(
                    SignalDecision(
                        symbol=sym, name=name, asset_class=internal_class,
                        action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                        buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                        reason=f"رصد خروج نهنگ ({wn:+.1f} م.ت) روی سهم؛ فعلاً ورود ممنوع."
                    )
                )
                continue

            if pct_last >= 4.7:
                decisions_out.append(
                    SignalDecision(
                        symbol=sym, name=name, asset_class=internal_class,
                        action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                        buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                        reason=f"نزدیک/قفل سقف روزانه ({pct_last:+.1f}%)؛ پرهیز از سرخطی و عبور خودکار به سهم‌های باز بعدی{extra_str}."
                    )
                )
                continue

            if sym in qualifying_syms:
                alloc_toman = round(self.total_capital_toman * (per_entry_weight / 100.0), 0)
                pos = self.store.open_virtual_position(
                    symbol=sym, name=name, asset_class=internal_class,
                    entry_price=last_price, entry_regime=regime.value,
                    allocated_toman=alloc_toman
                )
                decisions_out.append(
                    SignalDecision(
                        symbol=sym, name=name, asset_class=internal_class,
                        action="BUY_ENTRY", tracking_mode=pos.tracking_mode,
                        current_price=last_price, entry_price=last_price, peak_price=last_price,
                        trailing_stop_price=pos.compute_trailing_stop(),
                        buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                        suggested_weight_pct=per_entry_weight,
                        trigger_pillar=f"امتیاز ترکیبی تک‌سهم ({composite:.0f})",
                        reason=(
                            f"قدرت خریدار {buyer_power:.2f} و ورود پول حقیقی {net_inflow:+.1f} م.ت{extra_str}. "
                            f"ورود با وزن {per_entry_weight:.1f}% ({alloc_toman:,.0f} تومان)."
                        )
                    )
                )
            else:
                decisions_out.append(
                    SignalDecision(
                        symbol=sym, name=name, asset_class=internal_class,
                        action="WAIT", tracking_mode="WATCHLIST", current_price=last_price,
                        buyer_power=buyer_power, net_inflow_b_toman=net_inflow,
                        reason=f"تحت رصد در لیست ۵ سهم برتر؛ منتظر تقویت قدرت خریدار ({buyer_power:.2f}){extra_str}."
                    )
                )

        return decisions_out
