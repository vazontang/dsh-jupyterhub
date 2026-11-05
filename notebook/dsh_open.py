"""Jupyter Server extension: GET {base_url}dsh-open

Authenticated by Jupyter (only the server owner / Hub-authorised users reach it).
Starts DSH through jupyter-server-proxy if needed, then hands the browser the
per-process DSH launch token so DSH sets its own session cookie.
"""
import asyncio
import os
from pathlib import Path

from jupyter_server.base.handlers import JupyterHandler
from jupyter_server.utils import url_path_join
from tornado import web
from tornado.httpclient import AsyncHTTPClient, HTTPClientError

# Container-local (not on the home volume): a new pod never sees an old token.
LAUNCH_FILE = Path(os.environ.get("DSH_RUNTIME_DIR", f"/tmp/dsh-{os.getuid()}")) / "launch-url"
START_TIMEOUT = float(os.environ.get("DSH_OPEN_TIMEOUT", "90"))


class DshOpenHandler(JupyterHandler):
    @web.authenticated
    async def get(self):
        base = self.base_url  # e.g. /user/alice/
        if not LAUNCH_FILE.exists():
            await self._kick_proxy(base)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + START_TIMEOUT
        while not LAUNCH_FILE.exists():
            if loop.time() > deadline:
                raise web.HTTPError(504, "DSH did not start in time; see the server log")
            await asyncio.sleep(0.5)
        token = LAUNCH_FILE.read_text().strip()
        self.set_header("Cache-Control", "no-store")
        self.set_header("Referrer-Policy", "no-referrer")
        self.redirect(url_path_join(base, "dsh/") + "?token=" + token)

    async def _kick_proxy(self, base):
        """Hit our own /dsh/ once so jupyter-server-proxy launches dsh-launch."""
        port = self.settings["serverapp"].port
        token = os.environ.get("JUPYTERHUB_API_TOKEN") or getattr(self.identity_provider, "token", "")
        url = f"http://127.0.0.1:{port}{url_path_join(base, 'dsh/')}"
        try:
            resp = await AsyncHTTPClient().fetch(
                url, headers={"Authorization": f"token {token}"},
                request_timeout=START_TIMEOUT, follow_redirects=False, raise_error=False)
        except (HTTPClientError, OSError) as e:
            raise web.HTTPError(502, f"could not start DSH: {e}") from e
        # DSH itself answers 401 (no DSH cookie yet): that means it is up.
        if resp.code >= 500 or resp.code == 599:
            raise web.HTTPError(502, f"could not start DSH (proxy answered {resp.code}); see the server log")


def _jupyter_server_extension_points():
    return [{"module": "dsh_open"}]


def _load_jupyter_server_extension(serverapp):
    # DSH has not been started by this server yet: any launch-url left over is stale
    LAUNCH_FILE.unlink(missing_ok=True)
    serverapp.web_app.add_handlers(
        ".*$", [(url_path_join(serverapp.base_url, "dsh-open"), DshOpenHandler)])
    serverapp.log.info("dsh_open: %sdsh-open registered", serverapp.base_url)
