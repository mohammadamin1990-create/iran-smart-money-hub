"""
Bale Messenger (`tapi.bale.ai`) & Telegram (`api.telegram.org`) Bot Notifier.
Loads bot tokens safely from `.env` (project root or `~/.env`) without exposing secrets in code.
"""

import json
import os
from typing import Dict, List, Optional, Tuple
import urllib.request

from dynamic_daemon.entry_exit_engine import IntradayCycleReport, SignalDecision


def load_env_files(paths: List[str]) -> Dict[str, str]:
    """
    Lightweight, dependency-free .env parser supporting comments and quoted values.
    """
    env_vars: Dict[str, str] = {}
    for p in paths:
        expanded = os.path.expanduser(p)
        if not os.path.exists(expanded):
            continue
        try:
            with open(expanded, "r", encoding="utf-8-sig") as f:
                for line in f:
                    s = line.strip()
                    if not s or s.startswith("#") or "=" not in s:
                        continue
                    k, v = s.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip('"').strip("'")
                    if k and v:
                        env_vars[k] = v
        except Exception:
            pass
    # Environment variables set in OS override .env file if non-empty
    for key in (
        "BALE_BOT_TOKEN",
        "BALE_CHAT_ID",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_PROXY",
        "GEMINI_API_KEY",
        "CAPITAL_TOMAN",
        "SCAN_INTERVAL_MINUTES",
    ):
        if os.environ.get(key):
            env_vars[key] = os.environ[key]
    return env_vars


class BotNotifier:
    """
    Formats IntradayCycleReports into clean Persian messages and dispatches to Bale and/or Telegram.
    """

    ACTION_BADGES = {
        "BUY_ENTRY": "🟢 سیگنال ورود (خرید)",
        "EXIT": "🔴 سیگنال خروج فوری (فروش)",
        "SWITCH": "🔄 سیگنال سوییچ آربیتراژی",
        "HOLD": "🔵 نگهداری پوزیشن (Hold)",
        "WAIT": "⏳ دست نگه دارید (صبر برای نقطه بهینه)",
    }

    MODE_LABELS = {
        "MANUAL_REAL": "واقعی (ثبت‌شده شما)",
        "AUTO_VIRTUAL": "مجازی (رهگیری خودکار)",
        "WATCHLIST": "دیده‌بان ورود",
    }

    def __init__(self, env_path: Optional[str] = None):
        default_project_env = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", ".env")
        )
        search_paths = [ "~/.env", default_project_env ]
        if env_path:
            search_paths.append(env_path)
        self.config = load_env_files(search_paths)
        self.project_env_path = env_path or default_project_env

    @property
    def bale_configured(self) -> bool:
        return bool(self.config.get("BALE_BOT_TOKEN") and self.config.get("BALE_CHAT_ID"))

    @property
    def telegram_configured(self) -> bool:
        return bool(self.config.get("TELEGRAM_BOT_TOKEN") and self.config.get("TELEGRAM_CHAT_ID"))

    def format_cycle_message(self, report: IntradayCycleReport) -> str:
        """
        Builds a structured, easy-to-scan Persian message for Bale/Telegram.
        """
        lines: List[str] = []
        urgent = report.urgent_signals

        if urgent:
            lines.append("🚨 هـشـدار فـوری سیگنال ورود / خروج 🚨")
        else:
            lines.append("📊 گزارش دوره‌ای ۳۰ دقیقه‌ای موتور هوشمند بورس")

        lines.append(f"🕒 زمان: {report.timestamp}")
        lines.append(f"🏛 وضعیت تالار: {report.session.session_label}")
        lines.append("────────────────────")

        # 1. Macro & FX Summary
        lines.append(f"🧭 رژیم بازار: {report.regime.value}")
        if report.regime_changed:
            lines.append(f"⚠️ تغییر رژیم کلان از: «{report.previous_regime}»!")
        if report.spot_usd_rials > 0:
            lines.append(
                f"💵 دلار آزاد: {report.spot_usd_rials:,.0f} ریال | "
                f"دلار درهم: {report.implied_usd_rials:,.0f} ({report.dirham_spread_pct:+.2f}%)"
            )
        lines.append("────────────────────")

        # 2. Urgent Signals first (BUY_ENTRY / EXIT / SWITCH)
        if urgent:
            lines.append("⚡ اقدام‌های معاملاتی این نوبت:")
            for d in urgent:
                badge = self.ACTION_BADGES.get(d.action, d.action)
                mode_lbl = self.MODE_LABELS.get(d.tracking_mode, d.tracking_mode)
                lines.append(f"\n{badge} — نماد «{d.symbol}»")
                lines.append(f"• نوع ردیابی: {mode_lbl}")
                lines.append(f"• قیمت لحظه‌ای: {d.current_price:,.0f} ریال")
                if d.action == "BUY_ENTRY":
                    lines.append(f"• حد ضرر متحرک اولیه: {d.trailing_stop_price:,.0f} ریال")
                    lines.append(f"• وزن پیشنهادی سبد: {d.suggested_weight_pct:.0f}%")
                else:
                    lines.append(f"• قیمت ورود: {d.entry_price:,.0f} | بازده: {d.pnl_pct:+.2f}%")
                    lines.append(f"• معیار خروج: {d.trigger_pillar}")
                lines.append(f"• علت منطقی: {d.reason}")
            lines.append("────────────────────")

        # 3. Active Held Positions (HOLD)
        holds = [d for d in report.decisions if d.action == "HOLD"]
        if holds:
            lines.append("💼 پوزیشن‌های باز تحت پایش:")
            for d in holds:
                mode_lbl = "واقعی" if d.tracking_mode == "MANUAL_REAL" else "مجازی"
                lines.append(
                    f"🔵 {d.symbol} [{mode_lbl}] | قیمت: {d.current_price:,.0f} "
                    f"({d.pnl_pct:+.2f}%) | حد ضرر متحرک: {d.trailing_stop_price:,.0f} ریال"
                )

        # 4. Watchlist Waiting Items (WAIT)
        waits = [d for d in report.decisions if d.action == "WAIT"]
        if waits:
            lines.append("\n⏳ نمادهای سبد و واچ‌لیست در انتظار نقطه بهینه ورود:")
            for d in waits:
                p_str = f"{d.current_price:,.0f} ریال" if d.current_price > 0 else "تابلو بسته"
                lines.append(f"• {d.symbol} ({p_str}): {d.reason}")

        return "\n".join(lines)

    def send_bale(self, text: str) -> Tuple[bool, str]:
        token = self.config.get("BALE_BOT_TOKEN", "")
        chat_id = self.config.get("BALE_CHAT_ID", "")
        if not token or not chat_id:
            return False, "BALE_BOT_TOKEN یا BALE_CHAT_ID تنظیم نشده است."

        url = f"https://tapi.bale.ai/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": str(chat_id), "text": text}).encode("utf-8")
        direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        proxy_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"})
        )
        last_err = None
        for opener in (direct_opener, proxy_opener):
            req = urllib.request.Request(
                url, data=payload, headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}, method="POST"
            )
            try:
                with opener.open(req, timeout=12) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    if body.get("ok"):
                        return True, "پیام با موفقیت به بله ارسال شد."
                    return False, f"خطای API بله: {body}"
            except Exception as e:
                last_err = e
        return False, f"خطای شبکه در ارسال به بله: {last_err}"

    def send_telegram(self, text: str) -> Tuple[bool, str]:
        token = self.config.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = self.config.get("TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return False, "TELEGRAM_BOT_TOKEN یا TELEGRAM_CHAT_ID تنظیم نشده است."

        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({"chat_id": str(chat_id), "text": text}).encode("utf-8")

        proxy = self.config.get("TELEGRAM_PROXY", "http://127.0.0.1:10808")
        handlers = [urllib.request.ProxyHandler({"http": proxy, "https": proxy})] if proxy else []
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with opener.open(req, timeout=15) as resp:
                body = json.loads(resp.read().decode("utf-8"))
                if body.get("ok"):
                    return True, "پیام با موفقیت به تلگرام ارسال شد."
                return False, f"خطای API تلگرام: {body}"
        except Exception as e:
            return False, f"خطای شبکه در ارسال به تلگرام: {e}"

    def dispatch(self, text: str) -> Dict[str, Tuple[bool, str]]:
        """
        Sends text to all configured bot channels (Bale and/or Telegram).
        """
        results: Dict[str, Tuple[bool, str]] = {}
        if self.bale_configured:
            results["bale"] = self.send_bale(text)
        if self.telegram_configured:
            results["telegram"] = self.send_telegram(text)
        return results

    def discover_chat_id(self, platform: str = "bale") -> Tuple[Optional[str], str]:
        """
        Calls getUpdates on Bale or Telegram to automatically detect the user's chat_id
        after they send /start to their bot.
        """
        direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        proxy = self.config.get("TELEGRAM_PROXY", "http://127.0.0.1:10808")
        proxy_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": proxy, "https": proxy})
        )

        if platform == "bale":
            token = self.config.get("BALE_BOT_TOKEN", "")
            if not token:
                return None, "ابتدا BALE_BOT_TOKEN را در فایل .env ذخیره کنید."
            url = f"https://tapi.bale.ai/bot{token}/getUpdates"
            openers = (direct_opener, proxy_opener)
        else:
            token = self.config.get("TELEGRAM_BOT_TOKEN", "")
            if not token:
                return None, "ابتدا TELEGRAM_BOT_TOKEN را در فایل .env ذخیره کنید."
            url = f"https://api.telegram.org/bot{token}/getUpdates"
            openers = (proxy_opener, direct_opener)

        body = None
        last_err = None
        for opener in openers:
            try:
                req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
                with opener.open(req, timeout=12) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    break
            except Exception as e:
                last_err = e

        if body is None:
            return None, f"خطا در استعلام getUpdates: {last_err}"

        updates = body.get("result") or []
        if not updates:
            return None, "هیچ پیامی یافت نشد. لطفاً ابتدا در پیام‌رسان یک پیام (مثلاً /start) به بات خود بفرستید و دوباره امتحان کنید."
        last_msg = updates[-1].get("message") or updates[-1].get("channel_post") or {}
        chat = last_msg.get("chat") or {}
        cid = chat.get("id")
        if cid is not None:
            return str(cid), f"شناسه چت با موفقیت کشف شد: {cid}"
        return None, "ساختار پیام دریافتی فاقد chat.id بود."
