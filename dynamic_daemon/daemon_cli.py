"""
Iran Dynamic Intraday Signal & Position Lifecycle Daemon CLI.
Commands:
  - once     : Run one immediate analysis cycle (live or --demo) and dispatch alerts.
  - run      : Run continuous 30-minute scheduler loop during market hours.
  - buy      : Register a real manual buy position with exact execution price.
  - sell     : Close a tracked position and log realized P&L.
  - status   : View active portfolio positions (Real + Virtual) and closed history.
  - test-bot : Auto-discover Chat ID (if needed) and send a test message to Bale / Telegram.
"""

import argparse
import os
import sys
import time

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CORE_ENGINE_PATH = os.path.abspath(os.path.join(PROJECT_ROOT, "..", "iran_smart_money_engine"))
for p in (PROJECT_ROOT, CORE_ENGINE_PATH):
    if p not in sys.path:
        sys.path.insert(0, p)

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.analytics.fx_macro_radar import FXMacroRadar
from src.scanner_cli import create_demo_dataset

from dynamic_daemon.market_calendar import TehranMarketCalendar
from dynamic_daemon.position_store import HybridPositionStore
from dynamic_daemon.entry_exit_engine import IntradayEntryExitEngine, IntradayCycleReport
from dynamic_daemon.bot_notifier import BotNotifier
from dynamic_daemon.live_feed import LiveMarketFeed


console = Console(force_terminal=True, legacy_windows=False)


def infer_asset_class_by_symbol(symbol: str) -> str:
    sym = symbol.strip()
    if sym in ("عیار", "طلا", "کهربا", "گوهر", "نفیس", "مثقال", "زر", "جواهر", "زرفام", "گلدا", "دفینه"):
        return "صندوق طلا"
    if sym in ("اهرم", "شتاب", "توان", "جهش", "موج", "بیدار", "پیشران", "دوایکس", "نارنج"):
        return "صندوق اهرمی"
    if sym in ("افران", "ارمغان", "آسان", "کاردان", "کاریس", "لبخند", "کمند", "امین یکم"):
        return "صندوق درآمد ثابت"
    return "سهام و حق تقدم"


def render_cycle_to_console(report: IntradayCycleReport, bot_results: dict, source_label: str = "") -> None:
    console.print()
    src_line = f"\n[green]📡 منبع داده: {source_label}[/green]" if source_label else ""
    console.print(
        Panel.fit(
            f"[bold cyan]⚡ موتور دینامیک سیگنال ورود و خروج درون‌روزی (بازه ۳۰ دقیقه‌ای)[/bold cyan]\n"
            f"[white]🕒 زمان: {report.timestamp}   |   🏛 تالار: {report.session.session_label}[/white]\n"
            f"[yellow]🧭 رژیم کلان: {report.regime.value}[/yellow]   |   "
            f"[cyan]اسپرد درهم: {report.dirham_spread_pct:+.2f}%[/cyan]{src_line}",
            border_style="cyan"
        )
    )

    table = Table(title="📡 جدول تصمیم‌گیری منطقی ورود، نگهداری و خروج (Real + Virtual)", header_style="bold magenta")
    table.add_column("نماد", justify="right", style="bold yellow")
    table.add_column("طبقه", justify="right")
    table.add_column("نوع ردیابی", justify="center")
    table.add_column("فرمان موتور", justify="center")
    table.add_column("قیمت لحظه‌ای", justify="center")
    table.add_column("ورود / بازده", justify="center")
    table.add_column("حد ضرر متحرک", justify="center", style="red")
    table.add_column("حباب زنده", justify="center")
    table.add_column("قدرت خریدار", justify="center")
    table.add_column("منطق تصمیم / ستون ماشه", justify="right")

    action_styles = {
        "BUY_ENTRY": "[bold green]🟢 ورود (BUY)[/bold green]",
        "EXIT": "[bold red]🔴 خروج فوری (EXIT)[/bold red]",
        "SWITCH": "[bold yellow]🔄 سوییچ آربیتراژی[/bold yellow]",
        "HOLD": "[bold blue]🔵 نگهداری (HOLD)[/bold blue]",
        "WAIT": "[dim]⏳ صبر (WAIT)[/dim]",
    }

    for d in report.decisions:
        entry_str = f"{d.entry_price:,.0f} ({d.pnl_pct:+.2f}%)" if d.entry_price > 0 else "—"
        trail_str = f"{d.trailing_stop_price:,.0f}" if d.trailing_stop_price > 0 else "—"
        mode_str = "واقعی" if d.tracking_mode == "MANUAL_REAL" else ("مجازی" if d.tracking_mode == "AUTO_VIRTUAL" else "دیده‌بان")
        reason_full = f"[{d.trigger_pillar}] {d.reason}" if d.trigger_pillar else d.reason

        price_str = f"{d.current_price:,.0f}" if d.current_price > 0 else "تابلو بسته"
        table.add_row(
            d.symbol,
            d.asset_class,
            mode_str,
            action_styles.get(d.action, d.action),
            price_str,
            entry_str,
            trail_str,
            f"{d.live_bubble_pct:+.1f}%",
            f"{d.buyer_power:.2f}",
            reason_full
        )

    console.print(table)

    if bot_results:
        for ch, (ok, msg) in bot_results.items():
            color = "green" if ok else "red"
            console.print(f"[{color}]📨 ارسال به پیام‌رسان ({ch}): {msg}[/{color}]")
    else:
        console.print("[dim]ℹ️ بات بله/تلگرام هنوز در فایل .env تنظیم نشده است (نمایش در کنسول و ذخیره در لاگ انجام شد).[/dim]")


def execute_single_cycle(
    store: HybridPositionStore,
    capital_toman: float,
    use_demo: bool = False,
    force_open: bool = False,
    alerts_only: bool = False
) -> IntradayCycleReport | None:
    session = TehranMarketCalendar.get_session_state(force_open=force_open or use_demo)

    if use_demo:
        df = create_demo_dataset()
        source_label = "دیتاست شبیه‌سازی آزمایشی (--demo)"
    else:
        df, source_label = LiveMarketFeed().fetch_snapshot()
        if df.empty:
            console.print(
                "[bold red]⚠️ ارتباط با هر دو منبع زنده (TSETMC و سرور ابری فاندبیس) موقتاً برقرار نشد. "
                "برای جلوگیری از صدور سیگنال اشتباه، این سیکل بدون تغییر در سبد رد شد.[/bold red]"
            )
            return None

    fx_snap = None
    try:
        fx_snap = FXMacroRadar().analyze_macro_spread()
    except Exception:
        pass

    engine = IntradayEntryExitEngine(store=store, total_capital_toman=capital_toman)
    report = engine.evaluate_cycle(
        df=df,
        fx_snap=fx_snap,
        session=session,
        enrich_fundbase=not use_demo
    )

    # Append cycle log
    log_dir = os.path.join(PROJECT_ROOT, "state")
    os.makedirs(log_dir, exist_ok=True)
    notifier = BotNotifier()
    formatted_msg = notifier.format_cycle_message(report)
    with open(os.path.join(log_dir, "signals_history.log"), "a", encoding="utf-8") as lf:
        lf.write(formatted_msg + "\n" + ("=" * 60) + "\n")

    bot_results = {}
    if not alerts_only or report.urgent_signals:
        bot_results = notifier.dispatch(formatted_msg)

    render_cycle_to_console(report, bot_results, source_label=source_label)
    return report


def cmd_status(store: HybridPositionStore) -> None:
    if not store.positions:
        console.print("[yellow]هیچ پوزیشن بازی (واقعی یا مجازی) در حال حاضر ثبت نشده است.[/yellow]")
    else:
        t = Table(title="💼 پوزیشن‌های فعال تحت پایش موتور", header_style="bold cyan")
        t.add_column("نماد", style="bold yellow")
        t.add_column("طبقه دارایی")
        t.add_column("نوع ردیابی")
        t.add_column("قیمت ورود (ریال)", justify="center")
        t.add_column("سقف تجربه شده", justify="center")
        t.add_column("حد ضرر متحرک فعلی", justify="center", style="red")
        t.add_column("سرمایه (تومان)", justify="center")
        t.add_column("زمان ورود", justify="center")
        for p in store.positions.values():
            t.add_row(
                p.symbol,
                p.asset_class,
                "واقعی (ثبت شما)" if p.tracking_mode == "MANUAL_REAL" else "مجازی (خودکار)",
                f"{p.entry_price:,.0f}",
                f"{p.peak_price:,.0f}",
                f"{p.compute_trailing_stop():,.0f}",
                f"{p.allocated_toman:,.0f}" if p.allocated_toman > 0 else "—",
                p.entry_time
            )
        console.print(t)

    if store.closed_history:
        ht = Table(title="📜 آخرین معاملات بسته‌شده", header_style="bold green")
        ht.add_column("نماد", style="bold yellow")
        ht.add_column("نوع")
        ht.add_column("ورود", justify="center")
        ht.add_column("خروج", justify="center")
        ht.add_column("بازده قطعی", justify="center")
        ht.add_column("علت خروج", justify="right")
        for c in store.closed_history[-10:]:
            col = "green" if c.realized_pnl_pct >= 0 else "red"
            ht.add_row(
                c.symbol,
                "واقعی" if c.tracking_mode == "MANUAL_REAL" else "مجازی",
                f"{c.entry_price:,.0f}",
                f"{c.exit_price:,.0f}",
                f"[{col}]{c.realized_pnl_pct:+.2f}%[/{col}]",
                c.exit_reason
            )
        console.print(ht)


def save_key_to_env(env_path: str, key: str, value: str) -> None:
    lines = []
    found = False
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8-sig") as f:
            for line in f:
                if line.strip().startswith(f"{key}="):
                    lines.append(f"{key}={value}\n")
                    found = True
                else:
                    lines.append(line)
    if not found:
        lines.append(f"{key}={value}\n")
    with open(env_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def cmd_test_bot() -> None:
    notifier = BotNotifier()
    # Auto-discover chat_id if token is present without chat_id
    if notifier.config.get("BALE_BOT_TOKEN") and not notifier.config.get("BALE_CHAT_ID"):
        cid, msg = notifier.discover_chat_id("bale")
        console.print(f"[cyan]بله: {msg}[/cyan]")
        if cid:
            save_key_to_env(notifier.project_env_path, "BALE_CHAT_ID", cid)
            notifier = BotNotifier()

    if notifier.config.get("TELEGRAM_BOT_TOKEN") and not notifier.config.get("TELEGRAM_CHAT_ID"):
        cid, msg = notifier.discover_chat_id("telegram")
        console.print(f"[cyan]تلگرام: {msg}[/cyan]")
        if cid:
            save_key_to_env(notifier.project_env_path, "TELEGRAM_CHAT_ID", cid)
            notifier = BotNotifier()

    if not notifier.bale_configured and not notifier.telegram_configured:
        console.print(
            "[yellow]⚠️ هیچ بات فعالی در فایل .env یافت نشد. ابتدا اسکریپت setup_bot.ps1 را اجرا کنید تا توکن بات امن ذخیره شود.[/yellow]"
        )
        return

    test_msg = (
        "✅ اتصال بات موتور دینامیک سیگنال بورس با موفقیت برقرار شد!\n"
        "از این پس گزارش‌های ۳۰ دقیقه‌ای و سیگنال‌های منطقی ورود و خروج (بر اساس ۴ ستون خروج: پول درشت، تغییر رژیم، حد ضرر متحرک و حباب زنده) به این چت ارسال می‌شوند."
    )
    res = notifier.dispatch(test_msg)
    for ch, (ok, msg) in res.items():
        col = "green" if ok else "red"
        console.print(f"[{col}]{ch}: {msg}[/{col}]")


def main() -> None:
    parser = argparse.ArgumentParser(description="Iran Dynamic Intraday Entry/Exit Signal Daemon")
    sub = parser.add_subparsers(dest="command")

    # once
    p_once = sub.add_parser("once", help="اجرای یک نوبت تحلیل فوری و صدور سیگنال")
    p_once.add_argument("--demo", action="store_true", help="استفاده از دیتاست آزمایشی")
    p_once.add_argument("--force", action="store_true", help="بررسی فعال حتی خارج از ساعت بازار")
    p_once.add_argument("--capital", type=float, default=10_000_000.0, help="کل سرمایه به تومان (پیش‌فرض: ۱۰ میلیون)")
    p_once.add_argument("--alerts-only", action="store_true", help="ارسال پیام به بات فقط در صورت وجود سیگنال ورود/خروج")

    # run
    p_run = sub.add_parser("run", help="اجرای پیوسته هر ۳۰ دقیقه در ساعات بازار")
    p_run.add_argument("--interval", type=int, default=30, help="فاصله زمانی اسکن به دقیقه (پیش‌فرض: ۳۰)")
    p_run.add_argument("--capital", type=float, default=10_000_000.0, help="کل سرمایه به تومان")
    p_run.add_argument("--force", action="store_true", help="اسکن حتی در خارج از ساعات بازار")
    p_run.add_argument("--alerts-only", action="store_true", help="ارسال پیام به بات فقط هنگام سیگنال ورود/خروج")

    # buy
    p_buy = sub.add_parser("buy", help="ثبت دستی خرید واقعی شما با قیمت دقیق")
    p_buy.add_argument("--symbol", required=True, help="نماد (مثلاً عیار، شتاب، نوری)")
    p_buy.add_argument("--price", type=float, required=True, help="قیمت خرید به ریال")
    p_buy.add_argument("--toman", type=float, default=0.0, help="مبلغ سرمایه‌گذاری شده به تومان")
    p_buy.add_argument("--asset-class", default="", help="طبقه دارایی (اختیاری)")

    # sell
    p_sell = sub.add_parser("sell", help="ثبت دستی فروش و بستن پوزیشن")
    p_sell.add_argument("--symbol", required=True, help="نماد فروخته‌شده")
    p_sell.add_argument("--price", type=float, required=True, help="قیمت فروش به ریال")

    # status
    sub.add_parser("status", help="نمایش پوزیشن‌های باز (واقعی + مجازی) و سابقه معاملات")

    # test-bot
    sub.add_parser("test-bot", help="کشف خودکار Chat ID و ارسال پیام تست به بله / تلگرام")

    args = parser.parse_args()
    store = HybridPositionStore()

    if args.command == "buy":
        ac = args.asset_class or infer_asset_class_by_symbol(args.symbol)
        rec = store.register_manual_buy(
            symbol=args.symbol.strip(),
            entry_price=args.price,
            allocated_toman=args.toman,
            asset_class=ac
        )
        console.print(
            f"[bold green]✅ خرید واقعی «{rec.symbol}» در قیمت {rec.entry_price:,.0f} ریال ثبت شد "
            f"(حد ضرر متحرک اولیه: {rec.compute_trailing_stop():,.0f} ریال).[/bold green]"
        )
    elif args.command == "sell":
        closed = store.close_position(args.symbol.strip(), args.price, reason="ثبت فروش قطعی توسط کاربر")
        if closed:
            console.print(
                f"[bold cyan]🏁 پوزیشن «{closed.symbol}» بسته شد | بازده قطعی: {closed.realized_pnl_pct:+.2f}%[/bold cyan]"
            )
        else:
            console.print(f"[yellow]پوزیشن بازی با نماد «{args.symbol}» یافت نشد.[/yellow]")
    elif args.command == "status":
        cmd_status(store)
    elif args.command == "test-bot":
        cmd_test_bot()
    elif args.command == "run":
        console.print(
            f"[bold green]🚀 دیمون پایش هوشمند با گام زمانی هر {args.interval} دقیقه فعال شد (توقف با Ctrl+C)...[/bold green]"
        )
        while True:
            session = TehranMarketCalendar.get_session_state(force_open=args.force)
            if session.any_session_active:
                try:
                    store.load()
                    execute_single_cycle(
                        store=store,
                        capital_toman=args.capital,
                        use_demo=False,
                        force_open=args.force,
                        alerts_only=args.alerts_only
                    )
                except Exception as e:
                    console.print(f"[red]⚠️ خطا در اجرای چرخه اسکن: {e}[/red]")
            else:
                console.print(
                    f"[dim]🕒 [{session.now_tehran.strftime('%H:%M')}] {session.session_label} — استراحت تا بررسی بعدی...[/dim]"
                )
            time.sleep(max(1, args.interval) * 60)
    else:
        # Default to 'once' if command is 'once' or omitted
        use_demo = getattr(args, "demo", False)
        force_open = getattr(args, "force", True)
        cap = getattr(args, "capital", 10_000_000.0)
        alerts_only = getattr(args, "alerts_only", False)
        execute_single_cycle(
            store=store,
            capital_toman=cap,
            use_demo=use_demo,
            force_open=force_open,
            alerts_only=alerts_only
        )


if __name__ == "__main__":
    main()
