"""
Live Quantitative Toolset bridging Engine 1 (iran_smart_money_engine) and Engine 2 (dynamic_daemon).
Used both by:
  1. Gemini 3.8 Flash Function Calling (conversational AI brain)
  2. Built-in Zero-Key Smart Persian Router (instant deterministic replies)
"""

import os
import sys
import tempfile
import shutil
from typing import Any, Dict, List, Optional

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.analytics.fx_macro_radar import FXMacroRadar
from src.analytics.leveraged_analytics import LeveragedFundAnalyzer
from src.data.fundbase_gold import FundbaseGoldClient
from src.data.fundbase_leveraged import FundbaseLeveragedClient
from src.data.fundbase_portfolio_search import FundbasePortfolioSearchClient
from src.data.fundbase_players import FundbasePlayersClient
from src.data.fund_tracker import FundTracker

from dynamic_daemon.live_feed import LiveMarketFeed
from dynamic_daemon.market_calendar import TehranMarketCalendar
from dynamic_daemon.position_store import HybridPositionStore
from dynamic_daemon.entry_exit_engine import IntradayEntryExitEngine
from dynamic_daemon.bot_notifier import BotNotifier
from dynamic_daemon.jalali import to_shamsi_datetime, to_shamsi_date, iso_or_str_to_shamsi


def normalize_fa(text: str) -> str:
    if not text:
        return ""
    return (
        text.replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", " ")
        .strip()
    )


def infer_asset_class(symbol: str) -> str:
    sym = normalize_fa(symbol)
    if sym in ("عیار", "طلا", "کهربا", "گوهر", "نفیس", "مثقال", "زر", "زرگر", "جواهر", "زرفام", "گلدا", "دفینه", "آلتون", "ناب"):
        return "صندوق طلا"
    if sym in ("اهرم", "شتاب", "توان", "جهش", "موج", "بیدار", "پیشران", "دوایکس", "نارنج"):
        return "صندوق اهرمی"
    if sym in ("افران", "ارمغان", "آسان", "کاردان", "کاریس", "لبخند", "کمند", "امین یکم"):
        return "صندوق درآمد ثابت"
    return "سهام و حق تقدم"


class LiveMarketToolkit:
    """Thread-safe wrapper exposing live analytical tools and portfolio actions."""

    def __init__(self, state_file: Optional[str] = None, default_capital_toman: float = 10_000_000.0):
        self.default_capital_toman = default_capital_toman
        self.state_file = state_file or os.path.join(PROJECT_ROOT, "state", "portfolio_state.json")

    def _get_store(self) -> HybridPositionStore:
        store = HybridPositionStore(state_file=self.state_file)
        store.load()
        return store

    def get_engine1_report(self) -> Dict[str, Any]:
        """
        Executes Engine 1: Macro Flow, USD/AED Parity Radar, Gold & Leveraged Valuation, and Top 5 Stocks.
        Returns complete structured dict and formatted Shamsi Persian report.
        """
        session = TehranMarketCalendar.get_session_state(force_open=True)
        now_dt = TehranMarketCalendar.now()
        shamsi_dt = to_shamsi_datetime(now_dt, full_words=True)

        # 1. FX Radar
        fx_snap = None
        fx_info = {}
        try:
            fx_snap = FXMacroRadar().analyze_macro_spread()
            fx_info = {
                "free_usd_toman": round(fx_snap.spot_usd_rials / 10.0, 0),
                "dirham_implied_usd_toman": round(fx_snap.implied_usd_from_aed / 10.0, 0),
                "dirham_spread_pct": round(fx_snap.dirham_arbitrage_spread_pct, 2),
                "signal": fx_snap.macro_regime_signal,
            }
        except Exception:
            pass

        # 2. Gold Arbitrage
        gold_data = self.get_gold_arbitrage()
        gold_funds = gold_data.get("gold_funds", [])

        # 3. Leveraged 5D Ranking
        lev_data = self.get_leveraged_ranking()
        leveraged_funds = lev_data.get("ranking", [])

        # 4. Top 5 Stocks from Fundbase 3M accumulation
        top_stocks = []
        try:
            ps = FundbasePortfolioSearchClient()
            buys_3m = ps.get_top_fund_buys(months=3, level="symbol", direction="buy", limit=15)
            for b in buys_3m:
                sym_clean = normalize_fa(b.name)
                if infer_asset_class(sym_clean) == "سهام و حق تقدم" and not sym_clean.startswith(("اراد", "اخزا", "تسه", "گام")):
                    top_stocks.append({
                        "symbol": b.name,
                        "net_buy_billion_toman_3m": round(b.net_value_billion_toman, 1),
                        "buyer_funds_count": b.buyer_count,
                        "weight_change_pct": round(b.weight_change, 3),
                    })
                if len(top_stocks) >= 5:
                    break
        except Exception:
            pass

        # 5. Asset Allocation Plan & Regime
        from src.analytics.asset_allocator import MultiRegimeAssetAllocator
        dirham_spr = fx_snap.dirham_arbitrage_spread_pct if fx_snap else 0.0
        alloc_plan = MultiRegimeAssetAllocator().generate_plan(
            equity_net_inflow_b_toman=0.0,
            buyer_power_ratio=1.0,
            dirham_spread_pct=dirham_spr,
        )
        regime_label = alloc_plan.regime.value
        alloc_weights = {a.asset_class: a.target_weight_pct for a in alloc_plan.allocations}

        notifier = BotNotifier()
        formatted_text = notifier.format_engine1_report(
            shamsi_datetime=shamsi_dt,
            regime_label=regime_label,
            alloc_weights=alloc_weights,
            fx_info=fx_info,
            gold_funds=gold_funds,
            leveraged_funds=leveraged_funds,
            top_stocks=top_stocks,
        )

        return {
            "ok": True,
            "shamsi_datetime": shamsi_dt,
            "regime": regime_label,
            "allocation_weights": alloc_weights,
            "fx_radar": fx_info,
            "gold_funds": gold_funds[:5],
            "leveraged_ranking": leveraged_funds[:5],
            "top_stocks": top_stocks,
            "formatted_report": formatted_text,
        }

    def get_engine2_report(self, capital_toman: float = 0.0) -> Dict[str, Any]:
        """
        Executes Engine 2: 30-Minute Dynamic Intraday Signal, Trailing Stop & Position Lifecycle.
        Returns complete structured dict and formatted Shamsi Persian report.
        """
        cap = capital_toman if capital_toman > 0 else self.default_capital_toman
        session_real = TehranMarketCalendar.get_session_state(force_open=False)
        session_eval = TehranMarketCalendar.get_session_state(force_open=True)

        df, source_label = LiveMarketFeed().fetch_snapshot()
        if df.empty:
            return {"ok": False, "error": "ارتباط با سرورهای داده زنده موقتاً برقرار نشد."}

        fx_snap = None
        try:
            fx_snap = FXMacroRadar().analyze_macro_spread()
        except Exception:
            pass

        tmp_dir = tempfile.mkdtemp(prefix="hub_engine2_")
        try:
            tmp_state = os.path.join(tmp_dir, "state.json")
            if os.path.exists(self.state_file):
                shutil.copy2(self.state_file, tmp_state)
            temp_store = HybridPositionStore(state_file=tmp_state)
            engine = IntradayEntryExitEngine(store=temp_store, total_capital_toman=cap)
            report = engine.evaluate_cycle(df=df, fx_snap=fx_snap, session=session_eval, enrich_fundbase=True)

            store_positions = self.get_portfolio_status().get("open_positions", [])
            notifier = BotNotifier()
            formatted_text = notifier.format_engine2_report(report=report, open_positions=store_positions)

            return {
                "ok": True,
                "shamsi_datetime": report.timestamp,
                "market_session": session_real.session_label,
                "data_source": source_label,
                "urgent_signals_count": len(report.urgent_signals),
                "decisions": [
                    {
                        "symbol": d.symbol,
                        "asset_class": d.asset_class,
                        "action": d.action,
                        "current_price": d.current_price,
                        "trailing_stop": d.trailing_stop_price,
                        "live_bubble_pct": round(d.live_bubble_pct, 2),
                        "buyer_power": round(d.buyer_power, 2),
                        "reason": d.reason,
                    }
                    for d in report.decisions
                ],
                "formatted_report": formatted_text,
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def run_live_market_scan(self, capital_toman: float = 0.0) -> Dict[str, Any]:
        """Runs a non-mutating live scan across Gold, Leveraged, Top 5 Stocks & Macro."""
        cap = capital_toman if capital_toman > 0 else self.default_capital_toman
        session_real = TehranMarketCalendar.get_session_state(force_open=False)
        session_eval = TehranMarketCalendar.get_session_state(force_open=True)

        df, source_label = LiveMarketFeed().fetch_snapshot()
        if df.empty:
            return {"ok": False, "error": "ارتباط با سرورهای داده زنده موقتاً برقرار نشد."}

        fx_snap = None
        try:
            fx_snap = FXMacroRadar().analyze_macro_spread()
        except Exception:
            pass

        # Use a temp copy of state so interactive chat queries off-hours don't create virtual positions
        tmp_dir = tempfile.mkdtemp(prefix="hub_scan_")
        try:
            tmp_state = os.path.join(tmp_dir, "state.json")
            if os.path.exists(self.state_file):
                shutil.copy2(self.state_file, tmp_state)
            temp_store = HybridPositionStore(state_file=tmp_state)
            engine = IntradayEntryExitEngine(store=temp_store, total_capital_toman=cap)
            report = engine.evaluate_cycle(df=df, fx_snap=fx_snap, session=session_eval, enrich_fundbase=True)
            formatted_text = BotNotifier().format_cycle_message(report)
            return {
                "ok": True,
                "market_session": session_real.session_label,
                "data_source": source_label,
                "regime": report.regime.value,
                "dirham_spread_pct": round(report.dirham_spread_pct, 2),
                "formatted_report": formatted_text,
                "decisions": [
                    {
                        "symbol": d.symbol,
                        "asset_class": d.asset_class,
                        "action": d.action,
                        "current_price": d.current_price,
                        "live_bubble_pct": round(d.live_bubble_pct, 2),
                        "buyer_power": round(d.buyer_power, 2),
                        "allocated_toman": d.allocated_toman,
                        "reason": d.reason,
                    }
                    for d in report.decisions
                ],
            }
        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    def analyze_symbol(self, symbol: str) -> Dict[str, Any]:
        """Deep 3-Layer inspection of any single stock or ETF symbol."""
        sym = normalize_fa(symbol).replace("نماد ", "").replace("سهم ", "").replace("صندوق ", "").strip()
        result: Dict[str, Any] = {
            "symbol": sym,
            "live_board": None,
            "gold_fund_metrics": None,
            "leveraged_fund_metrics": None,
            "mutual_funds_3m": None,
            "whale_transactions": [],
            "verdict": "",
        }

        # Layer 1: Live Board / ETF Snapshot
        df, source_label = LiveMarketFeed().fetch_snapshot()
        result["data_source"] = source_label
        if not df.empty and "symbol" in df.columns:
            norm_col = df["symbol"].astype(str).map(normalize_fa)
            matches = df[norm_col == sym]
            if matches.empty:
                matches = df[norm_col.str.contains(sym, regex=False, na=False)]
            if not matches.empty:
                row = matches.iloc[0]
                trade_val_bt = float(row.get("trade_value", 0.0) or 0.0) / 10_000_000_000.0
                ind_buy_cnt = max(1.0, float(row.get("ind_buy_count", 0.0) or 0.0))
                ind_sell_cnt = max(1.0, float(row.get("ind_sell_count", 0.0) or 0.0))
                ind_buy_vol = float(row.get("ind_buy_vol", 0.0) or 0.0)
                ind_sell_vol = float(row.get("ind_sell_vol", 0.0) or 0.0)
                bp = (ind_buy_vol / ind_buy_cnt) / (ind_sell_vol / ind_sell_cnt) if ind_sell_vol > 0 else 1.0
                nav_val = float(row.get("nav", 0.0) or 0.0)
                close_p = float(row.get("last_price", 0.0) or row.get("close_price", 0.0) or 0.0)
                bub = ((close_p - nav_val) / nav_val * 100.0) if nav_val > 0 else float(row.get("bubble_pct", 0.0) or 0.0)
                result["live_board"] = {
                    "matched_symbol": str(row.get("symbol", sym)),
                    "name": str(row.get("name", "")),
                    "price_rial": close_p,
                    "change_pct": round(float(row.get("close_change_pct", 0.0) or 0.0), 2),
                    "nav_rial": nav_val,
                    "live_bubble_pct": round(bub, 2),
                    "trade_value_billion_toman": round(trade_val_bt, 2),
                    "buyer_power": round(bp, 2),
                }

        # Check Gold ETF metrics if applicable
        try:
            gold_map = FundbaseGoldClient().get_latest_gold_metrics()
            for k, gm in gold_map.items():
                if normalize_fa(k) == sym:
                    result["gold_fund_metrics"] = {
                        "price_bubble_pct": round(gm.price_bubble, 2),
                        "total_bubble_pct": round(gm.total_bubble, 2),
                        "bar_bullion_pct": round(gm.bar_pct, 1),
                        "coin_pct": round(gm.coin_pct, 1),
                        "redemption_nav": gm.redemption_nav,
                    }
                    break
        except Exception:
            pass

        # Check Leveraged ETF metrics if applicable
        try:
            lev_map = FundbaseLeveragedClient().get_latest_leveraged_metrics()
            for k, lm in lev_map.items():
                if sym in normalize_fa(k) or normalize_fa(k) == sym:
                    result["leveraged_fund_metrics"] = {
                        "fund_name": k,
                        "real_leverage_ratio": round(lm.real_ratio, 2),
                        "nominal_leverage_ratio": round(lm.nominal_ratio, 2),
                        "price_bubble_pct": round(lm.price_bubble, 2),
                    }
                    break
        except Exception:
            pass

        # Layer 2: Mutual Fund 3-Month Accumulation / Distribution
        try:
            ps = FundbasePortfolioSearchClient()
            buys_3m = ps.get_top_fund_buys(months=3, level="symbol", direction="buy", limit=100)
            sells_3m = ps.get_top_fund_buys(months=3, level="symbol", direction="sell", limit=100)
            buys_1m = ps.get_top_fund_buys(months=1, level="symbol", direction="buy", limit=100)
            matched_3m = next((x for x in buys_3m if normalize_fa(x.name) == sym), None)
            if not matched_3m:
                matched_3m = next((x for x in sells_3m if normalize_fa(x.name) == sym), None)
            matched_1m = next((x for x in buys_1m if normalize_fa(x.name) == sym), None)
            hist = ps.get_symbol_weight_history(sym)

            if matched_3m or matched_1m or hist:
                item = matched_3m or matched_1m
                result["mutual_funds_3m"] = {
                    "net_buy_billion_toman_3m": round(matched_3m.net_value_billion_toman, 2) if matched_3m else 0.0,
                    "net_buy_billion_toman_1m": round(matched_1m.net_value_billion_toman, 2) if matched_1m else 0.0,
                    "buyer_funds_count": item.buyer_count if item else 0,
                    "total_holding_funds": item.total_funds_holding if item else 0,
                    "weight_change_pct": round(item.weight_change, 3) if item else 0.0,
                    "latest_portfolio_weight_pct": round(hist[-1].weight_pct, 3) if hist else 0.0,
                }
        except Exception:
            pass

        # Layer 3: Top-500 Whale Radar
        try:
            txs = FundbasePlayersClient().get_latest_transactions(limit=250)
            sym_txs = [t for t in txs if normalize_fa(t.symbol) == sym]
            result["whale_transactions"] = [
                {
                    "date": iso_or_str_to_shamsi(t.date),
                    "whale_alias": t.alias,
                    "side": "BUY" if t.is_buy else "SELL",
                    "value_billion_toman": round(t.value_billion_toman, 2),
                }
                for t in sym_txs[:6]
            ]
        except Exception:
            pass

        # Synthesize Quantitative Verdict
        gm = result["gold_fund_metrics"]
        lm = result["leveraged_fund_metrics"]
        lb = result["live_board"]
        mf = result["mutual_funds_3m"]
        whales = result["whale_transactions"]

        if gm:
            bub = lb["live_bubble_pct"] if lb else gm["price_bubble_pct"]
            if gm["bar_bullion_pct"] >= 85 and bub <= 1.5:
                result["verdict"] = f"🟢 مناسب ورود پله‌ای (صندوق طلای شمش‌محور {gm['bar_bullion_pct']:.0f}% با حباب جذاب {bub:+.2f}%)"
            elif bub >= 4.0:
                result["verdict"] = f"🔴 حباب بالا ({bub:+.2f}%) — احتیاط یا سوییچ به صندوق طلای کم‌حباب‌تر"
            else:
                result["verdict"] = f"🔵 نگهداری / متعادل (حباب {bub:+.2f}%، وزن شمش {gm['bar_bullion_pct']:.0f}%)"
        elif lm:
            bub = lb["live_bubble_pct"] if lb else lm["price_bubble_pct"]
            rr = lm["real_leverage_ratio"]
            if rr >= 1.6 and bub <= -15.0:
                result["verdict"] = f"🟢 جزو لیدرهای اهرمی (ضریب اهرم واقعی {rr:.2f}x و تخفیف NAV عالی {bub:+.1f}%) — ورود مشروط به قدرت خریدار >= 1.15 در تایم بازار"
            elif rr < 1.1:
                result["verdict"] = f"🔴 ضریب اهرم واقعی ضعیف ({rr:.2f}x) — عملاً خاصیت اهرمی خنثی شده است"
            else:
                result["verdict"] = f"⏳ میانه جدول اهرمی (اهرم واقعی {rr:.2f}x، حباب {bub:+.1f}%)"
        else:
            net_3m = mf["net_buy_billion_toman_3m"] if mf else 0.0
            whale_buys = sum(1 for w in whales if w["side"] == "BUY")
            whale_sells = sum(1 for w in whales if w["side"] == "SELL")
            if net_3m >= 200 and whale_buys >= whale_sells:
                result["verdict"] = f"🟢 حمایت قوی حقوقی/صندوق‌ها ({net_3m:+,.0f} میلیارد تومان در ۳ ماه) — ورود در تایم بازار با شرط قدرت خریدار >= 1.35 و عدم قفل صف خرید"
            elif net_3m < -50 or (whale_sells > whale_buys and whale_sells >= 2):
                result["verdict"] = f"🔴 هشدار عرضه حقوقی/نهنگ‌ها (برآیند صندوق‌ها: {net_3m:+,.0f} میلیارد تومان) — فعلاً صبر و اجتناب"
            elif abs(net_3m) < 25 and not whales:
                result["verdict"] = "⚠️ هشدار تله نقدشوندگی: نه ردپایی در معاملات ۵۰۰ نهنگ دارد و نه انباشت معناداری در صندوق‌ها؛ فقط در صورت ارزش معاملات زنده بالای ۱۵ میلیارد تومان و قدرت خریدار >= 1.35 بررسی شود."
            else:
                result["verdict"] = "⏳ خنثی / نیازمند رصد تابلو زنده (قدرت خریدار >= 1.35 در ساعت ۰۹:۰۰ تا ۱۲:۳۰)"

        return result

    def get_leveraged_ranking(self) -> Dict[str, Any]:
        """Returns 5D live ranking of all Iranian leveraged ETFs."""
        df, source_label = LiveMarketFeed().fetch_snapshot()
        lev_metrics = FundbaseLeveragedClient().get_latest_leveraged_metrics()
        if df.empty:
            return {"ok": False, "error": "داده زنده صندوق‌ها در دسترس نیست."}

        analyzer = LeveragedFundAnalyzer()
        candidates = analyzer.analyze(df, live_leverage_map=lev_metrics)
        items = []
        for idx, c in enumerate(candidates, 1):
            items.append({
                "rank": idx,
                "symbol": c.symbol,
                "price_rial": c.close_price,
                "bubble_pct": round(c.p_nav_bubble_pct, 2),
                "real_leverage": round(c.leverage_ratio, 2),
                "trade_value_billion_toman": round(c.trade_value_b_toman, 1),
                "buyer_power": round(c.buyer_power_ratio, 2),
                "score": round(c.catch_up_score, 1),
            })
        return {"ok": True, "source": source_label, "ranking": items}

    def get_gold_arbitrage(self) -> Dict[str, Any]:
        """Returns live Gold ETF ranking by physical bullion % and lowest live bubble."""
        df, source_label = LiveMarketFeed().fetch_snapshot()
        gold_map = FundbaseGoldClient().get_latest_gold_metrics()
        fx_info = {}
        try:
            snap = FXMacroRadar().analyze_macro_spread()
            fx_info = {
                "dirham_implied_usd_toman": round(snap.implied_usd_from_aed / 10.0, 0),
                "free_usd_toman": round(snap.spot_usd_rials / 10.0, 0),
                "dirham_spread_pct": round(snap.dirham_arbitrage_spread_pct, 2),
                "signal": snap.macro_regime_signal,
            }
        except Exception:
            pass

        live_price_map = {}
        if not df.empty and "symbol" in df.columns:
            for _, r in df.iterrows():
                live_price_map[normalize_fa(str(r.get("symbol", "")))] = r

        rows = []
        for sym, gm in gold_map.items():
            nsym = normalize_fa(sym)
            r = live_price_map.get(nsym)
            price = float(r.get("last_price", 0.0) or r.get("close_price", 0.0)) if r is not None else gm.close_price
            nav = float(r.get("nav", 0.0) or 0.0) if r is not None else gm.redemption_nav
            bub = ((price - nav) / nav * 100.0) if nav > 0 else gm.price_bubble
            tval_bt = (float(r.get("trade_value", 0.0) or 0.0) / 10_000_000_000.0) if r is not None else 0.0
            rows.append({
                "symbol": sym,
                "price_rial": price,
                "live_bubble_pct": round(bub, 2),
                "bar_bullion_pct": round(gm.bar_pct, 1),
                "coin_pct": round(gm.coin_pct, 1),
                "trade_value_billion_toman": round(tval_bt, 1),
            })

        rows.sort(key=lambda x: (-1 if x["bar_bullion_pct"] >= 85 else 0, x["live_bubble_pct"]))
        return {"ok": True, "source": source_label, "fx_macro": fx_info, "gold_funds": rows[:10]}

    def get_portfolio_status(self) -> Dict[str, Any]:
        """Returns open positions (Real + Virtual), trailing stops, and closed history."""
        store = self._get_store()
        return {
            "open_positions": [
                {
                    "symbol": p.symbol,
                    "asset_class": p.asset_class,
                    "mode": "واقعی (ثبت شما)" if p.tracking_mode == "MANUAL_REAL" else "مجازی خودکار",
                    "entry_price_rial": p.entry_price,
                    "peak_price_rial": p.peak_price,
                    "trailing_stop_rial": p.compute_trailing_stop(),
                    "allocated_toman": p.allocated_toman,
                    "entry_time": iso_or_str_to_shamsi(p.entry_time),
                }
                for p in store.positions.values()
            ],
            "recent_closed_trades": [
                {
                    "symbol": c.symbol,
                    "entry_price_rial": c.entry_price,
                    "exit_price_rial": c.exit_price,
                    "realized_pnl_pct": c.realized_pnl_pct,
                    "exit_reason": c.exit_reason,
                }
                for c in store.closed_history[-5:]
            ],
        }

    def register_real_buy(self, symbol: str, price_rial: float, amount_toman: float = 0.0) -> Dict[str, Any]:
        """Registers a real manual purchase and activates dynamic trailing stop monitoring."""
        sym = normalize_fa(symbol)
        if price_rial <= 0:
            return {"ok": False, "error": "قیمت خرید باید بزرگتر از صفر (به ریال) باشد."}
        store = self._get_store()
        ac = infer_asset_class(sym)
        rec = store.register_manual_buy(
            symbol=sym,
            entry_price=float(price_rial),
            allocated_toman=float(amount_toman or 0.0),
            asset_class=ac,
        )
        return {
            "ok": True,
            "symbol": rec.symbol,
            "asset_class": rec.asset_class,
            "entry_price_rial": rec.entry_price,
            "trailing_stop_rial": rec.compute_trailing_stop(),
            "allocated_toman": rec.allocated_toman,
        }

    def register_real_sell(self, symbol: str, price_rial: float) -> Dict[str, Any]:
        """Closes a tracked position and records realized P&L."""
        sym = normalize_fa(symbol)
        store = self._get_store()
        closed = store.close_position(sym, float(price_rial), reason="فروش ثبت‌شده توسط کاربر در بله")
        if not closed:
            return {"ok": False, "error": f"پوزیشن بازی با نماد «{sym}» در سبد فعال یافت نشد."}
        return {
            "ok": True,
            "symbol": closed.symbol,
            "entry_price_rial": closed.entry_price,
            "exit_price_rial": closed.exit_price,
            "realized_pnl_pct": closed.realized_pnl_pct,
        }
