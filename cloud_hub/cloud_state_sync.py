"""
Permanent Private Cloud State Backup & Restore (Hugging Face Private Dataset).
Ensures open portfolio positions, trailing stops, and chat memory survive any cloud container restart.
"""

import os
import shutil
import threading

_SYNC_LOCK = threading.Lock()
STATE_FILES = ("portfolio_state.json", "chat_memory.json", "bale_offset.json")


def get_sync_config():
    hf_token = os.environ.get("HF_TOKEN", "").strip()
    repo_id = os.environ.get("STATE_DATASET_REPO", "").strip()
    return hf_token, repo_id


def restore_state_from_cloud(state_dir: str) -> None:
    hf_token, repo_id = get_sync_config()
    if not hf_token or not repo_id:
        return
    try:
        from huggingface_hub import hf_hub_download

        os.makedirs(state_dir, exist_ok=True)
        for fname in STATE_FILES:
            try:
                cached = hf_hub_download(
                    repo_id=repo_id,
                    filename=fname,
                    repo_type="dataset",
                    token=hf_token,
                )
                shutil.copy2(cached, os.path.join(state_dir, fname))
                print(f"☁️ بازیابی وضعیت ابری انجام شد: {fname}")
            except Exception:
                # File may not exist on very first boot
                pass
    except Exception as e:
        print(f"[Cloud State Restore Notice] {e}")


def sync_file_to_cloud_async(local_path: str) -> None:
    hf_token, repo_id = get_sync_config()
    if not hf_token or not repo_id or not os.path.exists(local_path):
        return
    fname = os.path.basename(local_path)

    def _worker():
        with _SYNC_LOCK:
            try:
                from huggingface_hub import HfApi

                api = HfApi(token=hf_token)
                api.upload_file(
                    path_or_fileobj=local_path,
                    path_in_repo=fname,
                    repo_id=repo_id,
                    repo_type="dataset",
                    commit_message=f"Sync {fname}",
                )
            except Exception as e:
                print(f"[Cloud State Sync Notice] {e}")

    threading.Thread(target=_worker, daemon=True).start()
