# /etc/jupyter/jupyter_server_config.py  (notebook image)
c = get_config()  # noqa: F821

c.ServerApp.jpserver_extensions = {
    "jupyter_mcp_server": True,   # /user/<name>/mcp  (DSH -> Jupyter tools)
    "dsh_open": True,             # /user/<name>/dsh-open (token handoff)
    "jupyter_server_proxy": True,
}
# jupyter-mcp-server: operate on the live documents of this server (RTC)
c.JupyterMCPServerExtensionApp.document_url = "local"
c.JupyterMCPServerExtensionApp.code_sandbox_url = "local"

# Web terminal: login shell so ~/.bashrc, git config etc. apply
c.ServerApp.terminado_settings = {"shell_command": ["/bin/bash", "-l"]}

c.ServerProxy.servers = {
    "dsh": {
        "command": ["dsh-launch", "{port}", "{base_url}"],
        "timeout": 90,
        "absolute_url": False,
        # The browser's Host header is passed through unchanged (verified in the
        # PoC), so DSH's Host/Origin fence sees the public authority, which
        # dsh-launch adds with --trusted-host $DSH_PUBLIC_HOST.
        "launcher_entry": {
            "enabled": True,
            "title": "DeepSeek Harness",
            "path_info": "dsh-open",
            "icon_path": "/etc/dsh/dsh.svg",
        },
        "new_browser_tab": True,
    }
}
