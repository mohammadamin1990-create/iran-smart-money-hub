"""
Automated 1-Shot GitHub Cloud Deployer:
  1. Creates repository `{owner}/iran-smart-money-hub` on GitHub.
  2. Pushes the unified codebase (strictly excluding .env and state/) via GitHub Git Data REST API.
  3. Encrypts all secrets (BALE_BOT_TOKEN, BALE_CHAT_ID, GEMINI_API_KEY, HF_TOKEN, STATE_DATASET_REPO)
     using libsodium (PyNaCl) into GitHub Actions Secrets.
  4. Triggers the 24x7 GitHub Actions cloud workflow immediately!
"""

import base64
import json
import os
import sys
import time
from typing import Any, Dict, List

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import requests
from nacl import encoding, public
from dynamic_daemon.bot_notifier import BotNotifier


EXCLUDED_DIRS = {".git", "__pycache__", "state", ".pytest_cache"}
EXCLUDED_FILES = {".env"}


class GitHubCloudDeployer:
    def __init__(self, gh_token: str, proxy: str = "http://127.0.0.1:10808"):
        self.gh_token = gh_token.strip()
        self.sess = requests.Session()
        self.sess.trust_env = False
        self.sess.proxies = {"http": proxy, "https": proxy}
        self.sess.headers.update(
            {
                "Authorization": f"Bearer {self.gh_token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "IranSmartMoneyDeployer/1.0",
            }
        )

    def _req(self, method: str, path: str, **kwargs) -> requests.Response:
        url = f"https://api.github.com{path}"
        resp = self.sess.request(method, url, timeout=25, **kwargs)
        return resp

    def deploy(self, repo_name: str = "iran-smart-money-hub") -> str:
        me_r = self._req("GET", "/user")
        me_r.raise_for_status()
        owner = me_r.json()["login"]
        full_repo = f"{owner}/{repo_name}"
        print(f"✅ اتصال به گیت‌هاب تایید شد: {owner}")

        # 1. Create repo if needed (public=True gives unlimited free GitHub Actions minutes; secrets are encrypted)
        check_r = self._req("GET", f"/repos/{full_repo}")
        if check_r.status_code == 404:
            cr = self._req(
                "POST",
                "/user/repos",
                json={
                    "name": repo_name,
                    "description": "Iran Quantitative Market & Dynamic Signal Cloud Hub",
                    "private": False,
                    "auto_init": True,
                },
            )
            cr.raise_for_status()
            print(f"📦 مخزن گیت‌هاب ساخته شد: {full_repo}")
            time.sleep(2)
        else:
            print(f"📦 مخزن گیت‌هاب موجود است: {full_repo}")

        # 2. Push all clean project files as a single atomic commit on `main`
        ref_r = self._req("GET", f"/repos/{full_repo}/git/ref/heads/main")
        if ref_r.status_code == 404:
            # Initialize empty repo with README first if needed
            init_r = self._req(
                "PUT",
                f"/repos/{full_repo}/contents/README.md",
                json={
                    "message": "Initial commit",
                    "content": base64.b64encode(b"# Iran Smart Money Hub\n").decode("ascii"),
                },
            )
            init_r.raise_for_status()
            time.sleep(1)
            ref_r = self._req("GET", f"/repos/{full_repo}/git/ref/heads/main")
        ref_r.raise_for_status()
        base_commit_sha = ref_r.json()["object"]["sha"]

        commit_r = self._req("GET", f"/repos/{full_repo}/git/commits/{base_commit_sha}")
        commit_r.raise_for_status()
        base_tree_sha = commit_r.json()["tree"]["sha"]

        tree_items: List[Dict[str, Any]] = []
        for root, dirs, files in os.walk(PROJECT_ROOT):
            dirs[:] = [d for d in dirs if d not in EXCLUDED_DIRS]
            for fn in files:
                if fn in EXCLUDED_FILES or fn.endswith((".pyc", ".pyo")) or fn.startswith(".env"):
                    continue
                abs_p = os.path.join(root, fn)
                rel_p = os.path.relpath(abs_p, PROJECT_ROOT).replace("\\", "/")
                with open(abs_p, "rb") as f:
                    raw_bytes = f.read()
                blob_r = self._req(
                    "POST",
                    f"/repos/{full_repo}/git/blobs",
                    json={"content": base64.b64encode(raw_bytes).decode("ascii"), "encoding": "base64"},
                )
                blob_r.raise_for_status()
                tree_items.append(
                    {
                        "path": rel_p,
                        "mode": "100644",
                        "type": "blob",
                        "sha": blob_r.json()["sha"],
                    }
                )

        print(f"📤 آپلود {len(tree_items)} فایل کد و دانش‌پایه (بدون هیچ فایل محرمانه)...")
        new_tree_r = self._req(
            "POST",
            f"/repos/{full_repo}/git/trees",
            json={"base_tree": base_tree_sha, "tree": tree_items},
        )
        new_tree_r.raise_for_status()

        new_commit_r = self._req(
            "POST",
            f"/repos/{full_repo}/git/commits",
            json={
                "message": "Deploy Unified 24x7 Bale Conversational & Signal Hub",
                "tree": new_tree_r.json()["sha"],
                "parents": [base_commit_sha],
            },
        )
        new_commit_r.raise_for_status()
        new_sha = new_commit_r.json()["sha"]

        upd_r = self._req(
            "PATCH",
            f"/repos/{full_repo}/git/refs/heads/main",
            json={"sha": new_sha, "force": True},
        )
        upd_r.raise_for_status()
        print("✅ تمام کدهای موتور ۱، موتور ۲ و چت‌بات روی گیت‌هاب ثبت شد.")

        # 3. Encrypt & Upload Secrets to GitHub Actions
        pk_r = self._req("GET", f"/repos/{full_repo}/actions/secrets/public-key")
        pk_r.raise_for_status()
        pk_data = pk_r.json()
        pub_key = public.PublicKey(pk_data["key"].encode("utf-8"), encoding.Base64Encoder())

        cfg = BotNotifier().config
        hf_tok = cfg.get("HF_TOKEN", "").strip()
        secrets_to_set = {
            "BALE_BOT_TOKEN": cfg.get("BALE_BOT_TOKEN", "").strip(),
            "BALE_CHAT_ID": cfg.get("BALE_CHAT_ID", "").strip(),
            "GEMINI_API_KEY": cfg.get("GEMINI_API_KEY", "").strip(),
            "HF_TOKEN": hf_tok,
            "STATE_DATASET_REPO": "AminOF91/iran-smart-money-state",
            "CAPITAL_TOMAN": cfg.get("CAPITAL_TOMAN", "").strip() or "10000000",
        }
        for s_name, s_val in secrets_to_set.items():
            if not s_val:
                continue
            sealed_box = public.SealedBox(pub_key)
            encrypted = base64.b64encode(sealed_box.encrypt(s_val.encode("utf-8"))).decode("utf-8")
            sr = self._req(
                "PUT",
                f"/repos/{full_repo}/actions/secrets/{s_name}",
                json={"encrypted_value": encrypted, "key_id": pk_data["key_id"]},
            )
            sr.raise_for_status()
            print(f"🔐 سکرت رمزنگاری‌شده در GitHub Actions ذخیره شد: {s_name}")

        # 4. Enable workflow & dispatch immediately
        time.sleep(2)
        disp_r = self._req(
            "POST",
            f"/repos/{full_repo}/actions/workflows/bale_cloud_24x7.yml/dispatches",
            json={"ref": "main"},
        )
        if disp_r.status_code in (200, 204):
            print("🚀 سرور ابری ۲۴ ساعته در GitHub Actions با موفقیت استارت خورد!")
        else:
            print(f"⚠️ پاسخ استارت ورک‌فلو ({disp_r.status_code}): {disp_r.text}")

        return f"https://github.com/{full_repo}/actions"


if __name__ == "__main__":
    tok = os.environ.get("GITHUB_PAT", "").strip()
    if len(sys.argv) > 1:
        tok = sys.argv[1].strip()
    if not tok:
        print("Usage: python deploy_github.py <GITHUB_TOKEN>")
        sys.exit(1)
    url = GitHubCloudDeployer(tok).deploy()
    print(f"🌐 پنل مانیتورینگ زنده سرور ابری شما:\n{url}")
