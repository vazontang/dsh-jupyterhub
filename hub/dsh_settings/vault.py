"""Minimal OpenBao/Vault KV v2 writer for the settings service.

The service authenticates with the Kubernetes auth method (its pod's service
account) and holds a policy that can create/update secret/data/users/* but
cannot read it back. Set VAULT_TOKEN instead for local testing.
"""
import json
import os
import time

from tornado.httpclient import AsyncHTTPClient, HTTPRequest

VAULT_ADDR = os.environ.get("VAULT_ADDR", "http://openbao.openbao.svc:8200")
KV_MOUNT = os.environ.get("VAULT_KV_MOUNT", "secret")
K8S_ROLE = os.environ.get("VAULT_K8S_ROLE", "dsh-settings")
K8S_MOUNT = os.environ.get("VAULT_K8S_MOUNT", "kubernetes")
SA_TOKEN = "/var/run/secrets/kubernetes.io/serviceaccount/token"

_token = {"value": os.environ.get("VAULT_TOKEN", ""), "expires": float("inf") if os.environ.get("VAULT_TOKEN") else 0}


class VaultError(Exception):
    pass


async def _call(method, path, body=None, token=None):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Vault-Token"] = token
    req = HTTPRequest(f"{VAULT_ADDR}/v1/{path}", method=method, headers=headers,
                      body=json.dumps(body) if body is not None else None, request_timeout=10)
    resp = await AsyncHTTPClient().fetch(req, raise_error=False)
    if resp.code >= 400 or resp.code == 599:
        detail = resp.body.decode(errors="replace")[:300] if resp.body else str(resp.error)
        raise VaultError(f"{method} {path}: HTTP {resp.code} {detail}")
    return json.loads(resp.body) if resp.body else {}


async def _login():
    if _token["value"] and time.time() < _token["expires"] - 30:
        return _token["value"]
    with open(SA_TOKEN) as f:
        jwt = f.read().strip()
    out = await _call("POST", f"auth/{K8S_MOUNT}/login", {"role": K8S_ROLE, "jwt": jwt})
    _token["value"] = out["auth"]["client_token"]
    _token["expires"] = time.time() + out["auth"]["lease_duration"]
    return _token["value"]


async def write_user_secret(user, kind, data):
    """Replace secret/users/<user>/<kind> with `data` (dict of strings)."""
    token = await _login()
    await _call("POST", f"{KV_MOUNT}/data/users/{user}/{kind}", {"data": data}, token)


async def delete_user_secret(user, kind):
    token = await _login()
    await _call("DELETE", f"{KV_MOUNT}/metadata/users/{user}/{kind}", None, token)
