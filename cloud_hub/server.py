"""
Unified 24/7 Cloud Server & Interactive Bale Assistant:
  1. Two-Way Bale Messenger Polling Loop (answers user questions & manages portfolio 24/7).
  2. Automatic 30-Minute Intraday Signal Scheduler (Saturday–Wednesday 09:00–18:00 IRST).
  3. Lightweight HTTP Health Endpoint (0.0.0.0:$PORT, default 7860) for Cloud Hosting (HF Spaces / Railway / Render).
"""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
import sys
import threading
import time
import urllib.request
from typing import Any, Dict, Optional

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dynamic_daemon.bot_notifier import BotNotifier
from dynamic_daemon.daemon_cli import execute_single_cycle
from dynamic_daemon.market_calendar import TehranMarketCalendar
from dynamic_daemon.position_store import HybridPositionStore
from dynamic_daemon.jalali import to_shamsi_datetime
from cloud_hub.ai_brain import ConversationalMarketBrain
from cloud_hub.market_tools import LiveMarketToolkit
from cloud_hub.cloud_state_sync import restore_state_from_cloud, sync_file_to_cloud_async


RUNTIME_STATUS: Dict[str, Any] = {
    "started_at": "",
    "bale_listener_alive": False,
    "scheduler_alive": False,
    "gemini_ai_active": False,
    "last_scan_time": "هنوز اجرا نشده",
    "messages_handled": 0,
}


class CloudHealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health", "/status"):
            session = TehranMarketCalendar.get_session_state()
            payload = {
                "ok": True,
                "engine": "Iran Smart Money + Dynamic Signal Cloud Hub",
                "tehran_time_shamsi": session.shamsi_datetime,
                "market_session": session.session_label,
                **RUNTIME_STATUS,
            }
            body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Keep container logs clean from healthcheck noise
        return


class BaleInteractiveCloudDaemon:
    """Runs the 2-way Bale conversational agent + 30-min signal daemon concurrently."""

    def __init__(self):
        self.notifier = BotNotifier()
        self.bot_token = self.notifier.config.get("BALE_BOT_TOKEN", "").strip()
        self.owner_chat_id = str(self.notifier.config.get("BALE_CHAT_ID", "")).strip()
        self.gemini_key = (
            self.notifier.config.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_API_KEY", "").strip()
        )
        self.capital_toman = float(
            self.notifier.config.get("CAPITAL_TOMAN", "")
            or os.environ.get("CAPITAL_TOMAN", "10000000")
        )
        self.interval_minutes = int(
            self.notifier.config.get("SCAN_INTERVAL_MINUTES", "")
            or os.environ.get("SCAN_INTERVAL_MINUTES", "30")
        )
        self.state_dir = os.path.join(PROJECT_ROOT, "state")
        os.makedirs(self.state_dir, exist_ok=True)
        restore_state_from_cloud(self.state_dir)
        self.offset_file = os.path.join(self.state_dir, "bale_offset.json")

        self.toolkit = LiveMarketToolkit(
            state_file=os.path.join(self.state_dir, "portfolio_state.json"),
            default_capital_toman=self.capital_toman,
        )
        self.brain = ConversationalMarketBrain(toolkit=self.toolkit, gemini_api_key=self.gemini_key)

        self.direct_opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.proxy_opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({"http": "http://127.0.0.1:10808", "https": "http://127.0.0.1:10808"})
        )
        RUNTIME_STATUS["gemini_ai_active"] = bool(self.gemini_key)

    def _bale_api(self, method: str, payload: Optional[Dict[str, Any]] = None, timeout: int = 12) -> Dict[str, Any]:
        url = f"{BotNotifier.BALE_API_BASE}/bot{self.bot_token}/{method}"
        headers = {"Content-Type": "application/json", "User-Agent": "IranSmartMoneyCloudHub/2.0"}
        data = json.dumps(payload or {}).encode("utf-8") if payload is not None else None
        openers = (self.direct_opener,) if os.environ.get("CLOUD_MODE") == "1" else (self.direct_opener, self.proxy_opener)
        last_err = None
        for op in openers:
            try:
                req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
                with op.open(req, timeout=timeout) as resp:
                    return json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                last_err = e
        raise RuntimeError(f"Bale API error ({method}): {last_err}")

    def _load_offset(self) -> Optional[int]:
        if os.path.exists(self.offset_file):
            try:
                with open(self.offset_file, "r", encoding="utf-8") as f:
                    return int(json.load(f).get("offset", 0))
            except Exception:
                pass
        return None

    def _save_offset(self, offset: int) -> None:
        with open(self.offset_file, "w", encoding="utf-8") as f:
            json.dump({"offset": offset}, f)
        sync_file_to_cloud_async(self.offset_file)

    def send_bale_reply(self, chat_id: str, text: str) -> None:
        if not text:
            return
        # Split cleanly if message > 3800 chars
        chunks = [text[i : i + 3800] for i in range(0, len(text), 3800)]
        for ch in chunks:
            try:
                self._bale_api("sendMessage", {"chat_id": str(chat_id), "text": ch})
            except Exception as e:
                print(f"[Bale Send Error] {e}")

    def initialize_offset_if_needed(self) -> int:
        saved = self._load_offset()
        if saved is not None:
            return saved
        try:
            res = self._bale_api("getUpdates", {"limit": 50}, timeout=8)
            updates = res.get("result") or []
            if updates:
                next_off = max(int(u.get("update_id", 0)) for u in updates) + 1
                self._save_offset(next_off)
                return next_off
        except Exception:
            pass
        self._save_offset(0)
        return 0

    def run_bale_chat_loop(self) -> None:
        if not self.bot_token:
            print("⚠️ BALE_BOT_TOKEN یافت نشد؛ شنونده چت بله غیرفعال است.")
            return

        offset = self.initialize_offset_if_needed()
        RUNTIME_STATUS["bale_listener_alive"] = True
        print(f"💬 شنونده دوطرفه چت بله فعال شد (مالک مجاز: {self.owner_chat_id or 'خودکار'})...")

        while True:
            try:
                res = self._bale_api("getUpdates", {"offset": offset, "limit": 20}, timeout=12)
                updates = res.get("result") or []
                for upd in updates:
                    upd_id = int(upd.get("update_id", 0))
                    offset = max(offset, upd_id + 1)
                    self._save_offset(offset)

                    msg = upd.get("message") or {}
                    chat = msg.get("chat") or {}
                    incoming_chat_id = str(chat.get("id", "")).strip()
                    text = str(msg.get("text", "")).strip()
                    if not incoming_chat_id or not text:
                        continue

                    # Auto-lock owner_chat_id if not set yet; enforce strict owner check otherwise
                    if not self.owner_chat_id:
                        self.owner_chat_id = incoming_chat_id
                    elif incoming_chat_id != self.owner_chat_id:
                        continue

                    print(f"📩 پیام دریافتی در بله: {text}")
                    reply_text = self.brain.reply(incoming_chat_id, text)
                    self.send_bale_reply(incoming_chat_id, reply_text)
                    RUNTIME_STATUS["messages_handled"] = int(RUNTIME_STATUS["messages_handled"]) + 1
            except Exception as e:
                print(f"[Bale Poll Retry] {e}")
                time.sleep(4)
                continue

            time.sleep(2.0)

    def run_scheduler_loop(self) -> None:
        RUNTIME_STATUS["scheduler_alive"] = True
        store = HybridPositionStore(state_file=os.path.join(self.state_dir, "portfolio_state.json"))
        print(f"⏱ زمان‌بند خودکار سیگنال هر {self.interval_minutes} دقیقه فعال شد...")

        while True:
            try:
                session = TehranMarketCalendar.get_session_state(force_open=False)
                if session.any_session_active:
                    store.load()
                    execute_single_cycle(
                        store=store,
                        capital_toman=self.capital_toman,
                        use_demo=False,
                        force_open=False,
                        alerts_only=False,
                    )
                    RUNTIME_STATUS["last_scan_time"] = to_shamsi_datetime(session.now_tehran, full_words=False)
                else:
                    print(f"🕒 [{session.shamsi_datetime}] {session.session_label} — آماده پاسخگویی در چت بله...")
            except Exception as e:
                print(f"[Scheduler Error] {e}")

            # Self health-ping if SPACE_HOST is set on Hugging Face Spaces to prevent idle sleep
            space_host = os.environ.get("SPACE_HOST", "").strip()
            if space_host:
                try:
                    ping_headers = {"User-Agent": "KeepAlive/1.0"}
                    if os.environ.get("HF_TOKEN"):
                        ping_headers["Authorization"] = f"Bearer {os.environ['HF_TOKEN']}"
                    ping_req = urllib.request.Request(f"https://{space_host}/health", headers=ping_headers)
                    urllib.request.urlopen(ping_req, timeout=6).read()
                except Exception:
                    pass

            time.sleep(max(1, self.interval_minutes) * 60)

    def _trigger_github_relay_if_configured(self) -> None:
        gh_repo = os.environ.get("GITHUB_REPOSITORY", "").strip()
        gh_token = os.environ.get("GITHUB_TOKEN", "").strip()
        if not gh_repo or not gh_token:
            return
        url = f"https://api.github.com/repos/{gh_repo}/actions/workflows/bale_cloud_24x7.yml/dispatches"
        body = json.dumps({"ref": "main"}).encode("utf-8")
        headers = {
            "Authorization": f"Bearer {gh_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "IranSmartMoneyRelay/1.0",
        }
        try:
            req = urllib.request.Request(url, data=body, headers=headers, method="POST")
            with urllib.request.urlopen(req, timeout=10):
                print("🔄 چرخه بعدی سرور ابری GitHub Actions با موفقیت فراخوانی شد.")
        except Exception as e:
            print(f"[GitHub Relay Notice] {e}")

    def start(self, with_http_server: bool = True) -> None:
        RUNTIME_STATUS["started_at"] = to_shamsi_datetime(TehranMarketCalendar.now(), full_words=True)
        max_run_seconds = int(os.environ.get("MAX_RUN_SECONDS", "0") or "0")

        t_chat = threading.Thread(target=self.run_bale_chat_loop, name="BaleChatListener", daemon=True)
        t_sched = threading.Thread(target=self.run_scheduler_loop, name="IntradayScheduler", daemon=True)
        t_chat.start()
        t_sched.start()

        if max_run_seconds > 0:
            print(f"☁️ حالت رانر ابری زمان‌دار فعال شد (مدت این شیفت: {max_run_seconds} ثانیه قبل از تحویل خودکار شیفت بعدی)...")
            if with_http_server:
                port = int(os.environ.get("PORT", "7860"))
                httpd = HTTPServer(("0.0.0.0", port), CloudHealthHandler)
                threading.Thread(target=httpd.serve_forever, daemon=True).start()
            time.sleep(max_run_seconds)
            self._trigger_github_relay_if_configured()
            time.sleep(3)
            print("✅ پایان شیفت فعلی و تحویل به شیفت بعدی ابری.")
            return

        if with_http_server:
            port = int(os.environ.get("PORT", "7860"))
            httpd = HTTPServer(("0.0.0.0", port), CloudHealthHandler)
            print(f"🌐 سرور سلامت ابری روی پورت {port} آماده به کار شد (0.0.0.0:{port})")
            httpd.serve_forever()
        else:
            while True:
                time.sleep(60)


if __name__ == "__main__":
    daemon = BaleInteractiveCloudDaemon()
    daemon.start(with_http_server=True)
