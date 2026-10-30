"""
One-Click GitHub Device-Code Auth + Automated 24/7 Cloud Deployment.
Prints https://github.com/login/device + 8-letter code, waits for user approval,
then automatically deploys the repo, encrypts all secrets, and starts the 24/7 GitHub Actions server!
"""

import os
import sys
import time
import requests

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

CLIENT_ID = "178c6fc778ccc68e1d6a"  # Official GitHub CLI OAuth App
PROXY = "http://127.0.0.1:10808"


def main():
    sess = requests.Session()
    sess.trust_env = False
    sess.proxies = {"http": PROXY, "https": PROXY}
    headers = {"Accept": "application/json", "User-Agent": "IranSmartMoneyDeployer/1.0"}

    r = sess.post(
        "https://github.com/login/device/code",
        data={"client_id": CLIENT_ID, "scope": "repo workflow"},
        headers=headers,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()

    device_code = data["device_code"]
    user_code = data["user_code"]
    verification_uri = data["verification_uri"]
    interval = int(data.get("interval", 5)) + 1
    expires_in = int(data.get("expires_in", 899))

    print(f"GITHUB_VERIFY_URL={verification_uri}", flush=True)
    print(f"GITHUB_USER_CODE={user_code}", flush=True)

    deadline = time.time() + expires_in
    while time.time() < deadline:
        time.sleep(interval)
        tr = sess.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": CLIENT_ID,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            headers=headers,
            timeout=15,
        )
        tdata = tr.json()
        err = tdata.get("error")
        if err == "authorization_pending":
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err:
            print(f"❌ خطا در احراز هویت گیت‌هاب: {tdata}", flush=True)
            sys.exit(1)

        access_token = tdata.get("access_token")
        if access_token:
            print("✅ تایید گیت‌هاب دریافت شد! شروع استقرار خودکار روی سرور ابری گیت‌هاب...", flush=True)
            from deploy_github import GitHubCloudDeployer
            from dynamic_daemon.bot_notifier import BotNotifier

            actions_url = GitHubCloudDeployer(access_token, proxy=PROXY).deploy()
            print(f"🎉 استقرار کامل شد: {actions_url}", flush=True)
            BotNotifier().dispatch(
                "☁️🎉 تبریک! سرور ابری ۲۴ ساعته شما روی GitHub Actions با موفقیت مستقر و روشن شد!\n"
                "از این لحظه حتی اگر کامپیوتر شما خاموش باشد و همه پنجره‌ها بسته شوند:\n"
                "۱. هر ۳۰ دقیقه در ساعات بازار سیگنال ورود/خروج خودکار می‌گیرید.\n"
                "۲. هر ساعت از شبانه‌روز در همین چت بله می‌توانید آزادانه با هوش مصنوعی (Gemini 3.8 Flash + هر دو موتور) گفتگو کنید.\n"
                "۳. تمام خریدها و حافظه گفتگو در مخزن خصوصی شما رمزنگاری و ذخیره می‌شود."
            )
            return

    print("⏰ مهلت کد گیت‌هاب به پایان رسید.", flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
