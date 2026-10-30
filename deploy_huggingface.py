"""
One-Command Automated Cloud Deployer to Hugging Face Spaces (Free 24/7 Docker Cloud).
Uploads the unified codebase (strictly excluding .env and state/) and configures encrypted Space Secrets.
"""

import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dynamic_daemon.bot_notifier import BotNotifier


def deploy_to_hf_space(hf_token: str, space_name: str = "iran-smart-money-hub") -> str:
    # Route via local proxy if available in Iran
    os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:10808")
    os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:10808")

    from huggingface_hub import HfApi

    api = HfApi(token=hf_token.strip())
    me = api.whoami()
    username = me["name"]
    repo_id = f"{username}/{space_name}"
    state_repo_id = f"{username}/iran-smart-money-state"

    print(f"✅ احراز هویت ابری انجام شد: {username}")
    print(f"🔒 در حال ساخت مخزن خصوصی ذخیره دائمی پرتفوی و حافظه: {state_repo_id} ...")
    api.create_repo(
        repo_id=state_repo_id,
        repo_type="dataset",
        private=True,
        exist_ok=True,
    )

    print(f"🚀 در حال ساخت/به‌روزرسانی فضای ابری ۲۴ ساعته: {repo_id} ...")

    try:
        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="docker",
            private=True,
            exist_ok=True,
        )
        print("🔒 فضای ابری به صورت کاملاً خصوصی (Private Space) ایجاد شد.")
    except Exception:
        api.create_repo(
            repo_id=repo_id,
            repo_type="space",
            space_sdk="docker",
            private=False,
            exist_ok=True,
        )

    # Read local secrets safely without uploading .env
    cfg = BotNotifier().config
    secrets_map = {
        "BALE_BOT_TOKEN": cfg.get("BALE_BOT_TOKEN", "").strip(),
        "BALE_CHAT_ID": cfg.get("BALE_CHAT_ID", "").strip(),
        "GEMINI_API_KEY": cfg.get("GEMINI_API_KEY", "").strip(),
        "CAPITAL_TOMAN": cfg.get("CAPITAL_TOMAN", "").strip() or "10000000",
        "HF_TOKEN": hf_token.strip(),
        "STATE_DATASET_REPO": state_repo_id,
    }
    for secret_key, val in secrets_map.items():
        if val:
            api.add_space_secret(repo_id=repo_id, key=secret_key, value=val)
            print(f"🔐 سکرت رمزنگاری‌شده تنظیم شد: {secret_key}")

    api.upload_folder(
        folder_path=PROJECT_ROOT,
        repo_id=repo_id,
        repo_type="space",
        ignore_patterns=[
            ".env",
            ".env.*",
            "state/*",
            "state/**",
            "**/__pycache__/**",
            "**/*.pyc",
            ".git/**",
        ],
    )

    url = f"https://huggingface.co/spaces/{repo_id}"
    print(f"🎉 دیپلوی ابری با موفقیت کامل شد! آدرس سرور ۲۴ ساعته شما:\n{url}")
    return url


if __name__ == "__main__":
    tok = os.environ.get("HF_TOKEN", "").strip()
    if len(sys.argv) > 1:
        tok = sys.argv[1].strip()
    if not tok:
        print("Usage: python deploy_huggingface.py <HF_WRITE_TOKEN>")
        sys.exit(1)
    deploy_to_hf_space(tok)
