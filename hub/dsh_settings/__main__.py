"""Hub-managed service: the "DSH 設定" page at /services/dsh-settings/.

- AI provider / model / key and Git identity -> encrypted SQLite (store.py),
  injected as env by the Hub's pre_spawn_hook.
- Git PATs, registry, helm repo creds, SSH key -> Vault (write-only), fetched by
  the vault-fetch init container into tmpfs at server start.
"""
import asyncio
import base64
import json
import os
import re
import time
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519
from jupyterhub.services.auth import HubOAuthCallbackHandler, HubOAuthenticated
from jupyterhub.utils import url_path_join
from tornado import ioloop, web
from tornado.httpclient import AsyncHTTPClient, HTTPRequest

from . import vault
from .store import load_settings, save_settings

PREFIX = os.environ["JUPYTERHUB_SERVICE_PREFIX"]          # /services/dsh-settings/
HUB_API = os.environ["JUPYTERHUB_API_URL"]                # http://hub:8081/hub/api
USER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
SECRET_KINDS = ("git", "registry", "helm", "ssh")


def _mask(v):
    return f"已設定（…{v[-4:]}）" if v else "未設定"


def _docker_auths(rows):
    auths = {}
    for server, user, pw in rows:
        auths[server] = {"auth": base64.b64encode(f"{user}:{pw}".encode()).decode()}
    return json.dumps({"auths": auths}, indent=2)


def _rows(handler, prefix, fields, n=3):
    out = []
    for i in range(n):
        vals = [handler.get_body_argument(f"{prefix}_{f}_{i}", "").strip() for f in fields]
        if all(vals):
            out.append(vals)
        elif any(vals):
            raise web.HTTPError(400, f"{prefix} 第 {i + 1} 列欄位不完整")
    return out


class BaseHandler(HubOAuthenticated, web.RequestHandler):
    def username(self):
        user = self.get_current_user()
        if not user or not USER_RE.match(user["name"]):
            raise web.HTTPError(403, "unsupported user name")
        return user["name"]


class SettingsHandler(BaseHandler):
    @web.authenticated
    async def get(self):
        name = self.username()
        s = await load_settings(name)
        self.render("settings.html", s=s, user=name, mask=_mask, msg=self.get_argument("msg", ""),
                    hub_home="/hub/home", kinds=SECRET_KINDS)

    @web.authenticated
    async def post(self):
        name = self.username()
        s = await load_settings(name)
        section = self.get_body_argument("section")
        vault_state = s.setdefault("vault", {})
        if section == "ai":
            s["llm_mode"] = self.get_body_argument("llm_mode", "deepseek")
            s["llm_model"] = self.get_body_argument("llm_model", "").strip() or "deepseek-flash"
            s["llm_provider"] = self.get_body_argument("llm_provider", "").strip() or "gateway"
            s["llm_api"] = self.get_body_argument("llm_api", "openai-completions")
            s["llm_base_url"] = self.get_body_argument("llm_base_url", "").strip()
            if s["llm_mode"] == "custom" and not urlparse(s["llm_base_url"]).scheme.startswith("http"):
                raise web.HTTPError(400, "自訂模式需要 Base URL (http/https)")
            key = self.get_body_argument("llm_api_key", "").strip()
            if key:
                s["llm_api_key"] = key
            if self.get_body_argument("llm_api_key_clear", ""):
                s["llm_api_key"] = ""
            s["git_name"] = self.get_body_argument("git_name", "").strip()
            s["git_email"] = self.get_body_argument("git_email", "").strip()
            await save_settings(name, s)
        elif section == "git":
            rows = _rows(self, "git", ("host", "user", "token"))
            lines = [f"https://{u}:{t}@{h}" for h, u, t in rows]
            await vault.write_user_secret(name, "git", {"credentials": "\n".join(lines) + "\n"})
            vault_state["git"] = {"updated": time.time(), "summary": ", ".join(f"{u}@{h}" for h, u, _ in rows)}
            await save_settings(name, s)
        elif section == "registry":
            rows = _rows(self, "reg", ("server", "user", "password"))
            await vault.write_user_secret(name, "registry", {"docker_config": _docker_auths(rows)})
            vault_state["registry"] = {"updated": time.time(), "summary": ", ".join(f"{u}@{h}" for h, u, _ in rows)}
            await save_settings(name, s)
        elif section == "helm":
            repos = _rows(self, "helm", ("name", "url", "user", "password"))
            oci = _rows(self, "helmoci", ("server", "user", "password"))
            repo_yaml = "apiVersion: \"\"\ngenerated: \"0001-01-01T00:00:00Z\"\nrepositories:\n" + "".join(
                f"- name: {json.dumps(n)}\n  url: {json.dumps(u)}\n  username: {json.dumps(us)}\n"
                f"  password: {json.dumps(pw)}\n  caFile: \"\"\n  certFile: \"\"\n  keyFile: \"\"\n"
                f"  insecure_skip_tls_verify: false\n  pass_credentials_all: false\n"
                for n, u, us, pw in repos)
            await vault.write_user_secret(name, "helm", {"repositories": repo_yaml,
                                                         "registry_config": _docker_auths(oci)})
            vault_state["helm"] = {"updated": time.time(),
                                   "summary": ", ".join([r[0] for r in repos] + [o[0] for o in oci])}
            await save_settings(name, s)
        elif section == "ssh":
            action = self.get_body_argument("action")
            known_hosts = self.get_body_argument("known_hosts", "").strip()
            if action == "generate":
                key = ed25519.Ed25519PrivateKey.generate()
                priv = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH,
                                         serialization.NoEncryption()).decode()
            else:
                priv = self.get_body_argument("private_key", "").strip() + "\n"
                key = serialization.load_ssh_private_key(priv.encode(), password=None)
            pub = key.public_key().public_bytes(serialization.Encoding.OpenSSH,
                                                serialization.PublicFormat.OpenSSH).decode()
            pub = f"{pub} {name}@dsh-jupyterhub"
            await vault.write_user_secret(name, "ssh", {"private_key": priv, "public_key": pub,
                                                        "known_hosts": known_hosts + "\n" if known_hosts else ""})
            s["ssh_public_key"] = pub
            vault_state["ssh"] = {"updated": time.time(), "summary": pub.split()[0]}
            await save_settings(name, s)
        elif section in ("clear",):
            kind = self.get_body_argument("kind")
            if kind not in SECRET_KINDS:
                raise web.HTTPError(400)
            await vault.delete_user_secret(name, kind)
            vault_state.pop(kind, None)
            if kind == "ssh":
                s["ssh_public_key"] = ""
            await save_settings(name, s)
        else:
            raise web.HTTPError(400)
        msg = "已儲存。重新啟動 server 後生效。"
        if self.get_body_argument("restart", ""):
            ioloop.IOLoop.current().spawn_callback(restart_server, name)
            msg = "已儲存，正在重新啟動 server…"
        self.redirect(url_path_join(PREFIX, "") + "?msg=" + web.escape.url_escape(msg))


async def hub_api(method, path, body=None):
    req = HTTPRequest(url_path_join(HUB_API, path), method=method,
                      headers={"Authorization": f"token {os.environ['JUPYTERHUB_API_TOKEN']}"},
                      body=json.dumps(body) if body is not None else (None if method in ("GET", "DELETE") else "{}"),
                      allow_nonstandard_methods=True, request_timeout=60)
    return await AsyncHTTPClient().fetch(req, raise_error=False)


async def restart_server(name):
    await hub_api("DELETE", f"users/{name}/server")
    for _ in range(120):  # wait until the default server is fully stopped
        r = await hub_api("GET", f"users/{name}")
        if r.code == 200 and "" not in json.loads(r.body).get("servers", {}):
            break
        await asyncio.sleep(1)
    resp = await hub_api("POST", f"users/{name}/server")
    if resp.code not in (201, 202):
        print(f"dsh-settings: restart of {name} returned {resp.code}", flush=True)


def main():
    here = os.path.dirname(__file__)
    app = web.Application(
        [
            (PREFIX, SettingsHandler),
            (url_path_join(PREFIX, "oauth_callback"), HubOAuthCallbackHandler),
        ],
        template_path=os.path.join(here, "templates"),
        cookie_secret=os.urandom(32),
        xsrf_cookies=True,
        login_url=url_path_join(PREFIX, "oauth_callback"),
    )
    url = urlparse(os.environ["JUPYTERHUB_SERVICE_URL"])
    # In k8s the URL is http://hub:10101 (reached by the proxy pod), so bind all interfaces there.
    bind = os.environ.get("DSH_SETTINGS_BIND", url.hostname)
    app.listen(url.port, bind)
    print(f"dsh-settings listening on {bind}:{url.port}{PREFIX}", flush=True)
    ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()
