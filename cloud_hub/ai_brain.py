"""
Dual-Mode Conversational Brain for Bale Messenger:
  1. Gemini 3.8 Flash (`google-genai` Interactions API + Live Function Calling + Persistent Memory)
     active automatically whenever GEMINI_API_KEY is present.
  2. Built-in Smart Persian Quantitative Router (works immediately with zero extra API keys
     and serves as a resilient fallback).
"""

import json
import os
import re
from typing import Any, Callable, Dict, List, Optional

from cloud_hub.market_tools import LiveMarketToolkit, normalize_fa

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
KNOWLEDGE_FILE = os.path.join(PROJECT_ROOT, "KNOWLEDGE_BASE.md")
CHAT_MEMORY_FILE = os.path.join(PROJECT_ROOT, "state", "chat_memory.json")

PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def to_english_digits(s: str) -> str:
    return (s or "").translate(PERSIAN_DIGITS)


TOOL_DECLARATIONS = [
    {
        "type": "function",
        "name": "run_live_market_scan",
        "description": "اسکن کامل و زنده کل بازار (طلا، صندوق اهرمی، ۵ سهم برتر پول هوشمند و اسپرد درهم) و صدور سیگنال ورود/خروج.",
        "parameters": {
            "type": "object",
            "properties": {
                "capital_toman": {
                    "type": "number",
                    "description": "کل سرمایه کاربر به تومان (پیش‌فرض 10000000 تومان)",
                }
            },
        },
    },
    {
        "type": "function",
        "name": "analyze_symbol",
        "description": "تحلیل عمیق ۳ لایه هر نماد سهام یا صندوق (قیمت و حباب زنده، انباشت ۳ ماهه صندوق‌ها در فاندبیس، و معاملات ۵۰۰ نهنگ بازار).",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {
                    "type": "string",
                    "description": "نماد بورسی به فارسی مثل فولاد، آکو، بیدار، عیار، شتاب، فملی",
                }
            },
            "required": ["symbol"],
        },
    },
    {
        "type": "function",
        "name": "get_leveraged_ranking",
        "description": "رتبه‌بندی ۵ بعدی زنده تمام صندوق‌های اهرمی (بیدار، شتاب، اهرم، توان، جهش، دوایکس، موج) همراه با ضریب اهرم واقعی و حباب.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_gold_arbitrage",
        "description": "بررسی آربیتراژ زنده صندوق‌های طلا (عیار، طلا، کهربا، زرگر، گوهر و...)، درصد شمش و سکه، حباب لحظه‌ای و اسپرد درهم.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "get_portfolio_status",
        "description": "مشاهده پوزیشن‌های باز کاربر (خریدهای واقعی و مجازی)، قیمت ورود، حد ضرر متحرک فعلی و سابقه معاملات بسته شده.",
        "parameters": {"type": "object", "properties": {}},
    },
    {
        "type": "function",
        "name": "register_real_buy",
        "description": "ثبت خرید واقعی سهم یا صندوق توسط کاربر با قیمت خرید به ریال و قفل کردن حد ضرر متحرک روی قیمت واقعی او.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "نماد خریداری شده"},
                "price_rial": {"type": "number", "description": "قیمت خرید هر واحد/سهم به ریال"},
                "amount_toman": {"type": "number", "description": "مبلغ کل خرید به تومان (اختیاری)"},
            },
            "required": ["symbol", "price_rial"],
        },
    },
    {
        "type": "function",
        "name": "register_real_sell",
        "description": "ثبت فروش واقعی یک پوزیشن باز توسط کاربر به ریال و محاسبه سود/زیان قطعی.",
        "parameters": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string", "description": "نماد فروخته شده"},
                "price_rial": {"type": "number", "description": "قیمت فروش هر واحد/سهم به ریال"},
            },
            "required": ["symbol", "price_rial"],
        },
    },
]


class ConversationalMarketBrain:
    """Handles multi-turn Persian chat in Bale using Gemini 3.8 Flash + deterministic fallback."""

    def __init__(self, toolkit: Optional[LiveMarketToolkit] = None, gemini_api_key: Optional[str] = None):
        self.toolkit = toolkit or LiveMarketToolkit()
        self.gemini_api_key = (
            gemini_api_key
            or os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
        )
        self.system_instruction = self._load_knowledge_base()
        self.memory = self._load_memory()
        self.available_functions: Dict[str, Callable[..., Any]] = {
            "run_live_market_scan": self.toolkit.run_live_market_scan,
            "analyze_symbol": self.toolkit.analyze_symbol,
            "get_leveraged_ranking": self.toolkit.get_leveraged_ranking,
            "get_gold_arbitrage": self.toolkit.get_gold_arbitrage,
            "get_portfolio_status": self.toolkit.get_portfolio_status,
            "register_real_buy": self.toolkit.register_real_buy,
            "register_real_sell": self.toolkit.register_real_sell,
        }

    def _load_knowledge_base(self) -> str:
        if os.path.exists(KNOWLEDGE_FILE):
            try:
                with open(KNOWLEDGE_FILE, "r", encoding="utf-8") as f:
                    return f.read()
            except Exception:
                pass
        return "شما دستیار هوشمند بازار سرمایه ایران هستید."

    def _load_memory(self) -> Dict[str, Any]:
        if os.path.exists(CHAT_MEMORY_FILE):
            try:
                with open(CHAT_MEMORY_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"last_interaction_id": {}, "turns": []}

    def _save_memory(self) -> None:
        os.makedirs(os.path.dirname(CHAT_MEMORY_FILE), exist_ok=True)
        self.memory["turns"] = self.memory.get("turns", [])[-20:]
        with open(CHAT_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(self.memory, f, ensure_ascii=False, indent=2)
        try:
            from cloud_hub.cloud_state_sync import sync_file_to_cloud_async
            sync_file_to_cloud_async(CHAT_MEMORY_FILE)
        except Exception:
            pass

    def _record_turn(self, user_msg: str, bot_reply: str) -> None:
        self.memory.setdefault("turns", []).append({"user": user_msg, "assistant": bot_reply[:800]})
        self._save_memory()

    def reply(self, chat_id: str, user_message: str) -> str:
        clean_msg = normalize_fa(user_message)
        if not clean_msg:
            return "پیام خالی دریافت شد. می‌توانید نام هر سهم یا صندوقی را بپرسید یا بنویسید «سیگنال»."

        if clean_msg in ("/reset", "ریست حافظه"):
            self.memory["last_interaction_id"][str(chat_id)] = None
            self.memory["turns"] = []
            self._save_memory()
            return "🧹 حافظه کوتاه‌مدت گفتگو پاک‌سازی شد (قوانین هر دو موتور و پرتفوی شما کاملاً محفوظ است)."

        # Try full Gemini 3.8 Flash AI Brain if API key is configured
        if self.gemini_api_key:
            ai_ans = self._reply_via_gemini(str(chat_id), clean_msg)
            if ai_ans:
                self._record_turn(clean_msg, ai_ans)
                return ai_ans

        # Deterministic Smart Persian Router (Zero-Key & Resilient Fallback)
        det_ans = self._reply_deterministic(clean_msg)
        self._record_turn(clean_msg, det_ans)
        return det_ans

    def _reply_via_gemini(self, chat_id: str, user_message: str) -> Optional[str]:
        try:
            from google import genai
        except ImportError:
            return None

        # On local Windows in Iran (when CLOUD_MODE != '1'), route Gemini API through local proxy 127.0.0.1:10808
        if os.environ.get("CLOUD_MODE") != "1":
            os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:10808")
            os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:10808")

        client_kwargs: Dict[str, Any] = {"api_key": self.gemini_api_key}
        prev_id = self.memory.get("last_interaction_id", {}).get(chat_id)

        # Build recent context summary when starting a fresh interaction chain
        effective_input: Any = user_message
        if not prev_id and self.memory.get("turns"):
            recent_lines = []
            for t in self.memory["turns"][-6:]:
                recent_lines.append(f"کاربر: {t['user']}\nدستیار: {t['assistant']}")
            history_prefix = "خلاصه آخرین پیام‌های قبلی ما:\n" + "\n---\n".join(recent_lines)
            effective_input = f"{history_prefix}\n\nپیام جدید کاربر:\n{user_message}"

        for attempt in range(2):
            try:
                client = genai.Client(**client_kwargs)
                current_input = effective_input if attempt == 0 else user_message
                current_prev_id = prev_id if attempt == 0 else None

                # Multi-step tool execution loop (up to 4 sequential tool rounds)
                for _ in range(4):
                    create_kwargs: Dict[str, Any] = {
                        "model": "gemini-3.8-flash",
                        "input": current_input,
                        "system_instruction": self.system_instruction,
                        "tools": TOOL_DECLARATIONS,
                    }
                    if current_prev_id:
                        create_kwargs["previous_interaction_id"] = current_prev_id

                    interaction = client.interactions.create(**create_kwargs)

                    function_results = []
                    for step in getattr(interaction, "steps", []) or []:
                        if getattr(step, "type", "") == "function_call":
                            fn_name = step.name
                            fn_args = dict(step.arguments or {})
                            fn = self.available_functions.get(fn_name)
                            if fn:
                                try:
                                    res_obj = fn(**fn_args)
                                except Exception as fn_err:
                                    res_obj = {"ok": False, "error": str(fn_err)}
                            else:
                                res_obj = {"ok": False, "error": f"Unknown tool: {fn_name}"}

                            function_results.append(
                                {
                                    "type": "function_result",
                                    "name": fn_name,
                                    "call_id": step.id,
                                    "result": [
                                        {
                                            "type": "text",
                                            "text": json.dumps(res_obj, ensure_ascii=False),
                                        }
                                    ],
                                }
                            )

                    current_prev_id = interaction.id
                    if not function_results:
                        self.memory.setdefault("last_interaction_id", {})[chat_id] = interaction.id
                        self._save_memory()
                        out = (interaction.output_text or "").strip()
                        return out if out else None

                    current_input = function_results
            except Exception as e:
                # If previous_interaction_id expired on server, retry once with fresh chain
                if attempt == 0 and prev_id:
                    prev_id = None
                    continue
                print(f"[Gemini Fallback Notice] {e}")
                return None
        return None

    # ------------------------------------------------------------------
    # Built-in Zero-Key Smart Persian Router
    # ------------------------------------------------------------------
    def _reply_deterministic(self, msg: str) -> str:
        msg_en = to_english_digits(msg)
        lower = msg_en.lower()

        # 1. Help / Greeting
        if lower in ("/start", "/help", "سلام", "درود", "راهنما", "کمک", "منو"):
            ai_badge = "🟢 فعال (Gemini 3.8 Flash)" if self.gemini_api_key else "⚡ حالت دستیار هوشمند کمی (آماده ارتقا با GEMINI_API_KEY)"
            return (
                "سلام! من دستیار دوطرفه بازار سرمایه شما هستم (متصل به هر دو موتور «پول هوشمند + فاندبیس» و «سیگنال ۳۰ دقیقه‌ای»).\n"
                f"🧠 وضعیت مغز گفتگو: {ai_badge}\n\n"
                "هر زمان می‌توانید به فارسی طبیعی برایم بنویسید:\n"
                "• **«سیگنال»** یا **«الان چی بخرم؟»** ← اسکن زنده کل بازار و سبد پیشنهادی\n"
                "• **نام هر نماد** (مثلاً **«فولاد»**، **«آکو رو بخرم؟»**، **«عیار»**، **«بیدار»**) ← کالبدشکافی ۳ لایه زنده نماد\n"
                "• **«اهرمی»** ← جدول مقایسه زنده ضریب اهرم واقعی و حباب ۹ صندوق اهرمی\n"
                "• **«طلا»** ← آربیتراژ زنده صندوق‌های طلا، درصد شمش و اسپرد درهم\n"
                "• **«سبد»** یا **«وضعیت»** ← نمایش پوزیشن‌های باز و حد ضرر متحرک شما\n"
                "• **«خرید بیدار 63700 5000000»** ← ثبت خرید واقعی (قیمت ریال + مبلغ تومان)\n"
                "• **«فروش بیدار 68500»** ← ثبت فروش و محاسبه سود قطعی"
            )

        # 2. Register Buy: "خرید بیدار 63700 5000000" or "بیدار رو 63700 خریدم"
        buy_match = re.match(r"^خرید\s+([^\d\s]+)\s+(\d+(?:\.\d+)?)(?:\s+(\d+(?:\.\d+)?))?", msg_en)
        if not buy_match:
            buy_match = re.search(r"([^\d\s]+)\s+(?:را|رو)?\s*(?:در|روی|به قیمت)?\s*(\d{3,9})\s*خریدم", msg_en)
        if buy_match:
            sym = buy_match.group(1)
            price = float(buy_match.group(2))
            toman = float(buy_match.group(3)) if (buy_match.lastindex and buy_match.lastindex >= 3 and buy_match.group(3)) else 0.0
            res = self.toolkit.register_real_buy(sym, price, toman)
            if not res.get("ok"):
                return f"⚠️ {res.get('error')}"
            toman_str = f" | مبلغ: {res['allocated_toman']:,.0f} تومان" if res["allocated_toman"] > 0 else ""
            return (
                f"✅ خرید واقعی **«{res['symbol']}»** ({res['asset_class']}) ثبت شد!\n"
                f"• قیمت ورود شما: `{res['entry_price_rial']:,.0f}` ریال{toman_str}\n"
                f"• حد ضرر متحرک اولیه (Trailing Stop): `{res['trailing_stop_rial']:,.0f}` ریال\n"
                "از این لحظه در هر سیکل ۳۰ دقیقه‌ای با ۴ ستون خروج (پول درشت، رژیم کلان، حد ضرر متحرک و حباب) پایش می‌شود."
            )

        # 3. Register Sell: "فروش بیدار 68000" or "بیدار رو 68000 فروختم"
        sell_match = re.match(r"^فروش\s+([^\d\s]+)\s+(\d+(?:\.\d+)?)", msg_en)
        if not sell_match:
            sell_match = re.search(r"([^\d\s]+)\s+(?:را|رو)?\s*(\d{3,9})\s*فروختم", msg_en)
        if sell_match:
            sym = sell_match.group(1)
            price = float(sell_match.group(2))
            res = self.toolkit.register_real_sell(sym, price)
            if not res.get("ok"):
                return f"⚠️ {res.get('error')}"
            sign_emoji = "🟢" if res["realized_pnl_pct"] >= 0 else "🔴"
            return (
                f"🏁 فروش قطعی **«{res['symbol']}»** ثبت و پوزیشن بسته شد.\n"
                f"• ورود: `{res['entry_price_rial']:,.0f}` ریال | خروج: `{res['exit_price_rial']:,.0f}` ریال\n"
                f"• بازده قطعی: {sign_emoji} `{res['realized_pnl_pct']:+.2f}%`"
            )

        # 4. Portfolio Status
        if any(k in msg_en for k in ("سبد", "پرتفو", "وضعیت پوزیشن", "پوزیشن های من", "چی دارم")) or lower in ("وضعیت", "status"):
            st = self.toolkit.get_portfolio_status()
            lines = ["💼 **وضعیت سبد فعال تحت پایش موتور:**"]
            if not st["open_positions"]:
                lines.append("• در حال حاضر هیچ پوزیشن بازی ثبت نشده است.")
                lines.append("*(برای ثبت خرید واقعی بنویسید: `خرید نماد قیمت_ریال مبلغ_تومان`)*")
            else:
                for p in st["open_positions"]:
                    lines.append(
                        f"• **{p['symbol']}** ({p['mode']}) | ورود: `{p['entry_price_rial']:,.0f}` | "
                        f"سقف: `{p['peak_price_rial']:,.0f}` | حد ضرر متحرک: `{p['trailing_stop_rial']:,.0f}` ریال"
                    )
            if st["recent_closed_trades"]:
                lines.append("\n📜 **آخرین معاملات بسته شده:**")
                for c in st["recent_closed_trades"]:
                    lines.append(f"• {c['symbol']}: `{c['realized_pnl_pct']:+.2f}%` ({c['exit_reason']})")
            return "\n".join(lines)

        # 5. Full Market Scan / Signal Request
        if any(k in msg_en for k in ("سیگنال", "اسکن", "چی بخرم", "الان بخرم", "پیشنهاد خرید", "گزارش بازار")):
            scan = self.toolkit.run_live_market_scan()
            if not scan.get("ok"):
                return f"⚠️ {scan.get('error')}"
            return scan["formatted_report"]

        # 6. Leveraged ETF Ranking
        if any(k in msg_en for k in ("اهرمی", "صندوق های اهرمی", "مقایسه اهرمی")):
            rk = self.toolkit.get_leveraged_ranking()
            if not rk.get("ok"):
                return f"⚠️ {rk.get('error')}"
            lines = ["🚀 **رتبه‌بندی ۵ بعدی زنده صندوق‌های اهرمی:**"]
            for item in rk["ranking"][:8]:
                lines.append(
                    f"{item['rank']}. **{item['symbol']}** | امتیاز: `{item['score']}` | "
                    f"اهرم واقعی: `{item['real_leverage']}x` | حباب: `{item['bubble_pct']:+.1f}%` | "
                    f"ارزش معاملات: `{item['trade_value_billion_toman']}` م.ت"
                )
            lines.append("\n💡 *نکته: اولویت ورود با رتبه ۱ در صورت قدرت خریدار حقیقی بالای 1.15 در ساعت بازار (09:00 تا 12:30) است.*")
            return "\n".join(lines)

        # 7. Gold ETF Arbitrage
        if msg_en in ("طلا", "صندوق طلا", "حباب طلا", "شمش", "درهم") or "صندوق های طلا" in msg_en:
            gd = self.toolkit.get_gold_arbitrage()
            lines = ["🪙 **آربیتراژ زنده صندوق‌های طلا و رادار درهم:**"]
            fx = gd.get("fx_macro") or {}
            if fx:
                lines.append(
                    f"• دلار آزاد: `{fx.get('free_usd_toman', 0):,.0f}` ت | دلار ضمنی درهم: `{fx.get('dirham_implied_usd_toman', 0):,.0f}` ت "
                    f"(اسپرد: `{fx.get('dirham_spread_pct', 0):+.2f}%`)"
                )
            for g in gd.get("gold_funds", [])[:7]:
                lines.append(
                    f"• **{g['symbol']}** | قیمت: `{g['price_rial']:,.0f}` | حباب زنده: `{g['live_bubble_pct']:+.2f}%` | "
                    f"شمش: `{g['bar_bullion_pct']:.0f}%` | سکه: `{g['coin_pct']:.0f}%`"
                )
            return "\n".join(lines)

        # 8. Extract Symbol & Run 3-Layer Symbol Analysis
        cleaned = msg_en
        for noise in (
            "تحلیل", "بررسی", "سهم", "نماد", "صندوق", "وضعیت", "رو بخرم", "را بخرم",
            "بخرم یا نه", "بخرم", "بفروشم", "چطوره", "چطور است", "خوبه", "نظر", "چنده", "؟", "?", "!", "یا نه"
        ):
            cleaned = cleaned.replace(noise, " ")
        tokens = [t.strip() for t in cleaned.split() if t.strip() and t.strip() not in ("الان", "امروز", "فردا", "واسه", "برای", "در", "مورد")]
        if tokens and len(tokens[0]) <= 12:
            target_sym = tokens[0]
            info = self.toolkit.analyze_symbol(target_sym)
            return self._format_symbol_analysis(info)

        return (
            "متوجه منظورتان نشدم؛ نام دقیق نماد (مثل `فولاد`، `بیدار`، `عیار`، `آکو`) را بنویسید، "
            "یا یکی از کلیدواژه‌های `سیگنال`، `طلا`، `اهرمی`، `سبد` یا `راهنما` را ارسال کنید."
        )

    @staticmethod
    def _format_symbol_analysis(info: Dict[str, Any]) -> str:
        sym = info["symbol"]
        lines = [f"🔎 **کالبدشکافی ۳ لایه زنده نماد «{sym}»**"]

        lb = info.get("live_board")
        if lb:
            lines.append(
                f"\n📊 **تابلو زنده:**\n"
                f"• قیمت: `{lb['price_rial']:,.0f}` ریال (`{lb['change_pct']:+.2f}%`)\n"
                f"• حباب زنده: `{lb['live_bubble_pct']:+.2f}%` | قدرت خریدار: `{lb['buyer_power']:.2f}`\n"
                f"• ارزش معاملات: `{lb['trade_value_billion_toman']:,.1f}` میلیارد تومان"
            )
        else:
            lines.append("\n📊 **تابلو لحظه‌ای:** خارج از ساعت بازار سهام یا فاقد ردیف فعال در اسنپ‌شات فعلی")

        gm = info.get("gold_fund_metrics")
        if gm:
            lines.append(
                f"\n🪙 **ترکیب دارایی طلا (فاندبیس):** شمش فیزیکی `{gm['bar_bullion_pct']:.1f}%` | سکه `{gm['coin_pct']:.1f}%` | حباب کل `{gm['total_bubble_pct']:+.2f}%`"
            )

        lm = info.get("leveraged_fund_metrics")
        if lm:
            lines.append(
                f"\n⚡ **اهرم واقعی (فاندبیس):** ضریب اهرم موثر `{lm['real_leverage_ratio']:.2f}x` (اسمی `{lm['nominal_leverage_ratio']:.2f}x`) | حباب `{lm['price_bubble_pct']:+.2f}%`"
            )

        mf = info.get("mutual_funds_3m")
        if mf:
            lines.append(
                f"\n🏛 **ردپای صندوق‌های سرمایه‌گذاری (فاندبیس):**\n"
                f"• خالص خرید/فروش ۳ ماهه: `{mf['net_buy_billion_toman_3m']:+,.1f}` میلیارد تومان (۱ ماهه: `{mf['net_buy_billion_toman_1m']:+,.1f}` م.ت)\n"
                f"• تعداد صندوق‌های خریدار: `{mf['buyer_funds_count']}` از `{mf['total_holding_funds']}` صندوق سهامدار | وزن فعلی در پرتفوی صندوق‌ها: `{mf['latest_portfolio_weight_pct']:.3f}%`"
            )
        else:
            lines.append("\n🏛 **صندوق‌های سرمایه‌گذاری:** بدون حضور یا انباشت معنادار در ۱۰۰ نماد برتر صندوق‌ها")

        whales = info.get("whale_transactions") or []
        if whales:
            lines.append("\n🐋 **آخرین تحرکات ۵۰۰ نهنگ بازار روی این نماد:**")
            for w in whales[:4]:
                icon = "🟢 خرید" if w["side"] == "BUY" else "🔴 فروش"
                lines.append(f"• {w['date']} | {icon} توسط `{w['whale_alias']}` به ارزش `{w['value_billion_toman']:,.1f}` م.ت")
        else:
            lines.append("\n🐋 **رادار ۵۰۰ نهنگ:** هیچ معامله درشتی در ۲۵۰ تراکنش اخیر نهنگ‌ها روی این نماد ثبت نشده است.")

        lines.append(f"\n🎯 **جمع‌بندی منطقی موتور:**\n{info.get('verdict', '')}")
        return "\n".join(lines)
