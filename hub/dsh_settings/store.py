"""Per-user DSH settings, encrypted at rest with JUPYTERHUB_CRYPT_KEY.

Used by both the settings service (writes) and the Hub's pre_spawn_hook (reads).
Only the AI settings and non-secret metadata live here. Git/registry/helm/SSH
secrets go to Vault and are never stored by the Hub.
"""
import json
import os
import sqlite3
import time

from jupyterhub.crypto import decrypt, encrypt

DB_PATH = os.environ.get("DSH_SETTINGS_DB", "/srv/jupyterhub/dsh-settings.sqlite")

DEFAULTS = {
    "llm_mode": "deepseek",          # deepseek | custom
    "llm_model": "deepseek-flash",
    "llm_provider": "gateway",       # route name for custom mode
    "llm_api": "openai-completions", # openai-completions | openai-responses | anthropic-messages
    "llm_base_url": "",
    "llm_api_key": "",               # secret (encrypted in this DB)
    "git_name": "",
    "git_email": "",
    # non-secret status of what was written to Vault, for display only
    "vault": {},                     # kind -> {"updated": ts, "summary": "..."}
    "ssh_public_key": "",
}


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = sqlite3.connect(DB_PATH)
    db.execute("CREATE TABLE IF NOT EXISTS settings (user TEXT PRIMARY KEY, blob BLOB NOT NULL, updated REAL)")
    return db


async def load_settings(user):
    db = _connect()
    try:
        row = db.execute("SELECT blob FROM settings WHERE user = ?", (user,)).fetchone()
    finally:
        db.close()
    data = dict(DEFAULTS)
    if row:
        data.update(json.loads(await decrypt(row[0])))
    return data


async def save_settings(user, data):
    blob = await encrypt(json.dumps(data))
    db = _connect()
    try:
        with db:
            db.execute(
                "INSERT INTO settings (user, blob, updated) VALUES (?, ?, ?) "
                "ON CONFLICT(user) DO UPDATE SET blob = excluded.blob, updated = excluded.updated",
                (user, blob, time.time()))
    finally:
        db.close()


def spawn_env(s):
    """Environment for the user's server (consumed by dsh-launch and git)."""
    env = {"DSH_LLM_MODE": s["llm_mode"], "DSH_LLM_MODEL": s["llm_model"]}
    if s["llm_mode"] == "custom":
        env.update(DSH_LLM_PROVIDER=s["llm_provider"], DSH_LLM_API=s["llm_api"],
                   DSH_LLM_BASE_URL=s["llm_base_url"])
        if s["llm_api_key"]:
            env["DSH_LLM_API_KEY"] = s["llm_api_key"]
    elif s["llm_api_key"]:
        env["DEEPSEEK_API_KEY"] = s["llm_api_key"]
    if s["git_name"]:
        env["GIT_AUTHOR_NAME"] = env["GIT_COMMITTER_NAME"] = s["git_name"]
    if s["git_email"]:
        env["GIT_AUTHOR_EMAIL"] = env["GIT_COMMITTER_EMAIL"] = s["git_email"]
    return env
