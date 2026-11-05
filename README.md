# DSH × JupyterHub PoC（單台 k3s）

每位使用者登入（Keycloak OIDC）後拿到自己的 JupyterLab pod，裡面跑 DeepSeek Harness（DSH）web。
DSH 透過 MCP 把 Python / Bash 交給同一個 Jupyter 的 kernel 執行，使用者在 JupyterLab 看得到也能改。
AI key 存在 Hub（加密）；PAT / registry / helm / Git SSH key 存在 OpenBao，啟動時由 init container 取到記憶體，不落地到 home volume。

設計文件：https://claude.ai/artifact/4DdApcMw1Yop5hAWaPSwoA

## 目錄

| 路徑 | 內容 |
|---|---|
| `notebook/` | 使用者 image：Dockerfile（Node 24、DSH 0.2.2-rc.1、jupyter-mcp-server、jupyter-server-proxy）、`dsh-launch`、`dsh_open.py`、`jupyter_server_config.py`、`skills/jupyter-first`、系統層 gitconfig / ssh_config |
| `hub/` | Hub image：k8s-hub 4.4.4 ＋ `dsh_settings`（「DSH 設定」頁服務、加密儲存、spawn hook） |
| `vault-fetch/` | init container：Keycloak access token → OpenBao → `/run/user-secrets`（tmpfs） |
| `vault/` | OpenBao policy 與 `setup-openbao.sh` |
| `k8s/` | `values.yaml`（Z2JH 4.4.4）、`install.sh` |
| `openresty/hub.conf` | TLS、WebSocket、DSH cookie 路徑改寫 |

## 資料流

```
Browser ──https──> OpenResty :443 ──> NodePort 30080 (proxy-public) ──> hub / user pod
user pod:  JupyterLab :8888
             ├─ /user/<u>/dsh/      jupyter-server-proxy ──> dsh web (127.0.0.1:隨機 port)
             ├─ /user/<u>/dsh-open  拿 DSH launch token，302 給瀏覽器換 DSH cookie
             └─ /user/<u>/mcp       jupyter-mcp-server  <── DSH mcp-client（token = JUPYTERHUB_API_TOKEN）
           init container vault-fetch ──> OpenBao (JWT = 使用者的 Keycloak access token)
                                         └─> /run/user-secrets (emptyDir, medium=Memory)
hub pod:   JupyterHub + 「DSH 設定」服務 (/services/dsh-settings/)
             ├─ AI key / 模型 / Git 身分 → /srv/jupyterhub/dsh-settings.sqlite（JUPYTERHUB_CRYPT_KEY 加密）
             └─ PAT / registry / helm / SSH → OpenBao（只能寫，讀不回）
```

## 事前準備

- VM：Ubuntu 22.04/24.04，4 vCPU / 16 GB 以上（每人上限 2 CPU / 4 GB，可在 values.yaml 調），docker（只用來 build image）、OpenResty、`bao` CLI。
- 一個 DNS 名稱（例：`jhub.example.com`）和它的 TLS 憑證。不需要 wildcard。
- Keycloak realm 內：
  1. Client `jupyterhub`：confidential，Standard flow，Valid redirect URI `https://jhub.example.com/hub/oauth_callback`。
  2. Client scope mapper：**Audience** → 加入 `jupyterhub` 到 access token（OpenBao 用 `bound_audiences=jupyterhub` 驗）。
  3. Mapper：**Group Membership**，claim `groups`，關掉 full group path，加到 userinfo。
  4. Group `dsh-users`（可登入）、`dsh-admins`（Hub 管理員）。
- 把 `k8s/values.yaml`、`openresty/hub.conf` 裡的 `jhub.example.com`、`sso.example.com/realms/corp` 換成實際值。

## 安裝步驟

```bash
./k8s/install.sh k3s
./k8s/install.sh images
./k8s/install.sh openbao
./k8s/install.sh openbao-init      # 5 把 unseal key + root token：只顯示一次，請離線保存
export BAO_TOKEN=<root token>
KEYCLOAK_ISSUER=https://sso.example.com/realms/corp ./k8s/install.sh vault-config
./k8s/install.sh jhub              # 會問 Keycloak client secret
sudo cp openresty/hub.conf /etc/openresty/conf.d/ && sudo openresty -s reload
```

OpenBao 是手動 unseal：每次 openbao-0 重啟（含 VM 重開）後要 `./k8s/install.sh unseal`，輸入 5 把裡任 3 把。沒 unseal 的話，使用者 server 仍會啟動，但 `/run/user-secrets` 是空的（終端機會提示）。

## 使用者流程

1. 開 `https://jhub.example.com` → Keycloak 登入。
2. Hub 首頁 → Services → **dsh-settings**：填 AI 模式 / 模型 / API key、Git 名稱與 email；需要的話填 PAT、registry、helm repo，按「產生新金鑰」拿 SSH 公鑰貼到 GitLab/GitHub。按「儲存並重啟 server」。
3. JupyterLab Launcher → **DeepSeek Harness**（新分頁）。
4. 對 DSH 說「在 notebook 裡算…」，回到 JupyterLab 看 notebook 即時出現 cell 與輸出。
5. Web terminal：`git clone git@…`、`git push`、`helm repo update`、`helm push`（OCI）直接可用。

## 驗收標準

| # | 項目 | 怎麼驗 |
|---|---|---|
| 1 | OIDC：不在 `dsh-users` 的人進不來；`dsh-admins` 有 Admin 頁 | 兩個測試帳號 |
| 2 | DSH 可從 Launcher 開啟，不需要貼 token；重整、重啟 server 後仍正常 | 瀏覽器 |
| 3 | DSH 經 MCP 在 notebook 建 cell、執行、看到輸出（JupyterLab 同時開著會即時更新） | 對話「建立 notebook 算 6*7」 |
| 4 | 各人用自己的 AI key：A 改 key 不影響 B；home 目錄找不到 key | `grep -r <key 尾碼> ~` 無結果 |
| 5 | PAT / registry / helm / SSH key 只在 `/run/user-secrets`（`df` 看是 tmpfs），home 沒有；server 停掉就消失 | terminal |
| 6 | 隔離：A 的 pod 用自己的 token 讀不到 `secret/users/B/*`；設定頁的 service token 讀不回任何 secret | `bao kv get` 得 403 |
| 7 | DSH 的 cookie 路徑是 `/user/<自己>/dsh/`、帶 Secure | 瀏覽器 DevTools |
| 8 | 20 個帳號同時開 server，資源夠用 | `kubectl top pods -n jhub` |

## 已在開發機實測過的部分（2026-11-05）

用本機 JupyterHub 5.5.4 ＋ jupyter_server 2.x ＋ DSH 0.2.2-rc.1 ＋ OpenBao 2.4 dev server ＋ nginx 1.24（取代 k8s 與 Keycloak，以本機簽的 JWT 模擬 access token）：

- 瀏覽器 → nginx → Hub → Jupyter → jupyter-server-proxy → DSH：頁面、WebSocket（`/api/remote.mux`）正常，DSH cookie 被改寫成 `Path=/user/alice/dsh/`。
- jupyter-server-proxy 會原樣轉送 Host，DSH 的 Host/Origin 檢查只要 `--trusted-host` 就過，不需要 Host override。
- DSH（以 mock LLM 觸發工具呼叫）→ `mcp__jupyter__use_notebook` → `insert_execute_code_cell`：kernel 執行、輸出 `answer 42`，cell 存進 `work.ipynb`；DSH 看到 17 個 Jupyter 工具。
- 設定頁：儲存 AI / Git / registry / helm / SSH；SQLite 內沒有明文；service token 讀 Vault 得 403；「儲存並重啟」會重開 server 並帶入新 env。
- vault-fetch：alice 的 token 讀得到自己的、讀 bob 得 403、寫自己也 403；檔案權限 0600。
- 修正：launch token 檔原本放 home，重啟後會拿到舊 token（401），已改放容器內 `/tmp/dsh-$UID/` 並在 server 啟動時清掉。

## 尚未在 k8s 上驗證（PoC 要確認）

- `init_containers` 與 tmpfs volume 的實際掛載、uid 1000 權限。
- OpenBao kubernetes auth（hub service account `hub`）與 Keycloak JWT（Audience mapper）在真實 realm 的設定。
- Image 實際 build（Node 24 tarball、minimal-notebook python 3.12 的 site-packages 路徑）。
- 20 人同時使用時的 CPU / 記憶體。

## 已知限制 / 注意

- DSH 是 developer preview，版本鎖在 0.2.2-rc.1；升級前先在這套 PoC 跑一次驗收表。
- 使用者自己的 AI key、`JUPYTERHUB_API_TOKEN` 會出現在自己 server 的環境變數中（本人可見，他人不可見）。
- Keycloak access token 會出現在該使用者 pod spec 的 init container env（k8s 管理員可見，效期約 5 分鐘）。
- Git / registry / helm 每一類儲存時整組取代（設定頁只能寫，讀不回原值）。
- 不支援容器內 build image / Testcontainers（沒有 Docker daemon）。
