"""
پنجره گرافیکی امن و یک‌کلیکی برای اتصال بات «بله» یا «تلگرام» بدون نیاز به دستورات پیچیده ترمینال.
- توکن به صورت مخفی (•••) نمایش داده می‌شود و هرگز در چت یا لاگ چاپ نمی‌گردد.
- دکمه «چسباندن از کلیپ‌بورد» مشکل کیبورد فارسی (Ctrl+V) را کاملاً حل می‌کند.
- به صورت خودکار Chat ID شما را کشف و پیام تست را ارسال می‌کند.
"""

import os
import sys
import tkinter as tk
from tkinter import messagebox

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dynamic_daemon.bot_notifier import BotNotifier
from dynamic_daemon.daemon_cli import save_key_to_env


class BotSetupWindow:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("اتصال امن رادار بورس به پیام‌رسان بله / تلگرام")
        self.root.geometry("560x440")
        self.root.resizable(False, False)
        self.root.configure(bg="#1e293b")

        self.env_path = os.path.join(PROJECT_ROOT, ".env")
        self.platform_var = tk.StringVar(value="bale")
        self.token_var = tk.StringVar()

        # Header
        tk.Label(
            root,
            text="⚡ اتصال خودکار موتور سیگنال بورس به گوشی شما",
            font=("Tahoma", 12, "bold"),
            fg="#38bdf8",
            bg="#1e293b",
            pady=12,
        ).pack()

        # Quick 3-step instructions box
        guide_text = (
            "راهنمای ۳ مرحله‌ای ساده:\n"
            "۱) در بله (یا تلگرام) وارد @botfather شوید، دستور /newbot را بفرستید و توکن دریافتی را کپی کنید.\n"
            "   (نکته: آیدی ربات باید انگلیسی، یکتا و آخرش کلمه bot باشد؛ مثل: radare_man_77_bot)\n"
            "۲) وارد چت ربات جدیدی که ساختید شوید و حتماً یک‌بار دکمه «شروع» (/start) را بزنید.\n"
            "۳) در کادر پایین روی «چسباندن از کلیپ‌بورد» و سپس «ذخیره و ارسال پیام تست» کلیک کنید."
        )
        tk.Label(
            root,
            text=guide_text,
            font=("Tahoma", 9),
            fg="#e2e8f0",
            bg="#334155",
            justify="right",
            padx=12,
            pady=10,
            wraplength=510,
        ).pack(padx=18, pady=6, fill="x")

        # Platform radio buttons
        plat_frame = tk.Frame(root, bg="#1e293b")
        plat_frame.pack(pady=8)
        tk.Radiobutton(
            plat_frame,
            text="پیام‌رسان بله (بدون فیلترشکن)",
            variable=self.platform_var,
            value="bale",
            font=("Tahoma", 10, "bold"),
            fg="#4ade80",
            bg="#1e293b",
            selectcolor="#0f172a",
            activebackground="#1e293b",
            activeforeground="#4ade80",
        ).pack(side="right", padx=15)
        tk.Radiobutton(
            plat_frame,
            text="تلگرام (با پروکسی خودکار سیستم)",
            variable=self.platform_var,
            value="telegram",
            font=("Tahoma", 10, "bold"),
            fg="#60a5fa",
            bg="#1e293b",
            selectcolor="#0f172a",
            activebackground="#1e293b",
            activeforeground="#60a5fa",
        ).pack(side="right", padx=15)

        # Token input frame
        tk.Label(
            root,
            text="توکن ربات (به دلایل امنیتی به شکل مخفی ••• نمایش داده می‌شود):",
            font=("Tahoma", 9),
            fg="#cbd5e1",
            bg="#1e293b",
        ).pack(pady=(6, 2))

        entry_frame = tk.Frame(root, bg="#1e293b")
        entry_frame.pack(padx=18, pady=4, fill="x")

        self.token_entry = tk.Entry(
            entry_frame,
            textvariable=self.token_var,
            show="•",
            font=("Consolas", 11),
            bg="#0f172a",
            fg="#f8fafc",
            insertbackground="#f8fafc",
            relief="flat",
        )
        self.token_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))

        tk.Button(
            entry_frame,
            text="📋 چسباندن از کلیپ‌بورد",
            command=self.paste_clipboard,
            font=("Tahoma", 9, "bold"),
            bg="#475569",
            fg="#ffffff",
            relief="flat",
            padx=10,
            pady=5,
            cursor="hand2",
        ).pack(side="right")

        # Action button
        self.save_btn = tk.Button(
            root,
            text="✅ ذخیره امن، شناسایی خودکار اکانت و ارسال پیام تست",
            command=self.save_and_test,
            font=("Tahoma", 10, "bold"),
            bg="#16a34a",
            fg="#ffffff",
            activebackground="#15803d",
            activeforeground="#ffffff",
            relief="flat",
            padx=16,
            pady=10,
            cursor="hand2",
        )
        self.save_btn.pack(pady=14)

        # Status label
        self.status_lbl = tk.Label(
            root,
            text="آماده دریافت توکن...",
            font=("Tahoma", 9),
            fg="#fbbf24",
            bg="#1e293b",
            wraplength=510,
            justify="center",
        )
        self.status_lbl.pack(padx=18, pady=4)

    def paste_clipboard(self):
        try:
            clip = self.root.clipboard_get().strip()
            if clip:
                self.token_var.set(clip)
                self.status_lbl.config(
                    text=f"توکن از کلیپ‌بورد جای‌گذاری شد ({len(clip)} کاراکتر). اکنون دکمه سبز ذخیره و تست را بزنید.",
                    fg="#38bdf8",
                )
            else:
                self.status_lbl.config(text="کلیپ‌بورد خالی است! ابتدا توکن را در بله/تلگرام کپی کنید.", fg="#f87171")
        except Exception:
            self.status_lbl.config(text="متنی در کلیپ‌بورد یافت نشد. ابتدا توکن را کپی کنید.", fg="#f87171")

    def save_and_test(self):
        raw_token = self.token_var.get().strip().strip('"').strip("'")
        # Strip accidental "Token:" prefix if user copied extra text
        if ":" in raw_token and " " in raw_token:
            for part in raw_token.split():
                if ":" in part and len(part) > 20:
                    raw_token = part.strip()
                    break

        if not raw_token or ":" not in raw_token:
            messagebox.showwarning(
                "توکن نامعتبر",
                "لطفاً ابتدا توکن دریافتی از @botfather (که شامل عدد، دو نقطه : و حروف انگلیسی است) را کپی و جای‌گذاری کنید.",
            )
            return

        plat = self.platform_var.get()
        token_key = "BALE_BOT_TOKEN" if plat == "bale" else "TELEGRAM_BOT_TOKEN"
        chat_key = "BALE_CHAT_ID" if plat == "bale" else "TELEGRAM_CHAT_ID"
        plat_fa = "بله" if plat == "bale" else "تلگرام"

        self.status_lbl.config(text=f"در حال اتصال به سرور {plat_fa} و شناسایی اکانت شما...", fg="#fbbf24")
        self.root.update_idletasks()

        save_key_to_env(self.env_path, token_key, raw_token)
        notifier = BotNotifier(env_path=self.env_path)

        cid, msg = notifier.discover_chat_id(plat)
        if not cid:
            self.status_lbl.config(text=f"⚠️ توکن ذخیره شد، اما: {msg}", fg="#fbbf24")
            messagebox.showinfo(
                "نیاز به زدن دکمه شروع (/start)",
                f"توکن شما ذخیره شد!\n\nاما هنوز پیامی از سمت شما در ربات دیده نشد.\n"
                f"لطفاً وارد ربات جدیدتان در «{plat_fa}» شوید، یک بار دکمه «شروع» یا /start را بفرستید و دوباره همین دکمه سبز را بزنید.\n\nجزئیات: {msg}",
            )
            return

        save_key_to_env(self.env_path, chat_key, cid)
        notifier = BotNotifier(env_path=self.env_path)

        test_text = (
            "✅ تبریک! اتصال ربات موتور دینامیک سیگنال بورس با موفقیت برقرار شد!\n\n"
            "از این لحظه گزارش‌های ۳۰ دقیقه‌ای و سیگنال‌های منطقی ورود (🟢) و خروج ۴گانه (🔴 پول درشت، تغییر رژیم، حد ضرر متحرک و حباب زنده) مستقیماً به همین چت ارسال می‌شوند."
        )
        ok, send_msg = notifier.send_bale(test_text) if plat == "bale" else notifier.send_telegram(test_text)
        if ok:
            self.status_lbl.config(text=f"✅ اتصال به {plat_fa} با موفقیت کامل شد! گوشی خود را چک کنید.", fg="#4ade80")
            messagebox.showinfo("اتصال موفق!", f"پیام تست با موفقیت به «{plat_fa}» شما ارسال شد!\nمی‌توانید این پنجره را ببندید.")
        else:
            self.status_lbl.config(text=f"❌ خطا در ارسال پیام تست: {send_msg}", fg="#f87171")
            messagebox.showerror("خطای ارسال", send_msg)


def main():
    root = tk.Tk()
    BotSetupWindow(root)
    root.mainloop()


if __name__ == "__main__":
    main()
