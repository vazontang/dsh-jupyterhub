#!/usr/bin/env bash
# DSH x JupyterHub PoC on a single k3s VM.  Run step by step:
#   ./k8s/install.sh k3s          # k3s (no traefik/servicelb) + helm
#   ./k8s/install.sh images       # build 3 images with docker, import into k3s containerd
#   ./k8s/install.sh openbao      # OpenBao standalone (file storage on local-path PVC)
#   ./k8s/install.sh openbao-init # init (5 shares / threshold 3) + first unseal  -> keep the output offline!
#   ./k8s/install.sh unseal       # after every OpenBao pod restart (asks for 3 unseal keys)
#   ./k8s/install.sh vault-config # policies, jwt (Keycloak) + kubernetes auth   (needs BAO_TOKEN=<root>)
#   ./k8s/install.sh jhub         # secrets + Zero to JupyterHub
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${KEYCLOAK_ISSUER:=https://sso.example.com/realms/corp}"
export KUBECONFIG="${KUBECONFIG:-/etc/rancher/k3s/k3s.yaml}"
Z2JH_VERSION=4.4.4
OPENBAO_CHART_VERSION=0.30.6

step_k3s() {
  curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC="--disable traefik --disable servicelb --write-kubeconfig-mode 600" sh -
  command -v helm >/dev/null || curl -fsSL https://raw.githubusercontent.com/helm/helm/main/scripts/get-helm-3 | bash
  kubectl get nodes
}

step_images() {
  docker build -t dsh-notebook:poc "$ROOT/notebook"
  docker build -t jhub-dsh:poc     "$ROOT/hub"
  docker build -t vault-fetch:poc  "$ROOT/vault-fetch"
  for i in dsh-notebook:poc jhub-dsh:poc vault-fetch:poc; do
    docker save "$i" | sudo k3s ctr -n k8s.io images import -
  done
}

step_openbao() {
  helm repo add openbao https://openbao.github.io/openbao-helm >/dev/null
  helm repo update >/dev/null
  helm upgrade --install openbao openbao/openbao --version "$OPENBAO_CHART_VERSION" \
    -n openbao --create-namespace \
    --set server.standalone.enabled=true \
    --set server.dataStorage.storageClass=local-path \
    --set server.authDelegator.enabled=true \
    --set injector.enabled=false \
    --set ui.enabled=false
  kubectl -n openbao rollout status statefulset/openbao --timeout=180s || true
}

step_openbao_init() {
  echo ">>> The output below holds the 5 unseal keys and the root token. Store them OFFLINE"
  echo ">>> (e.g. 5 people / password manager). It is shown once and not saved by this script."
  kubectl -n openbao exec -i openbao-0 -- bao operator init -key-shares=5 -key-threshold=3
  step_unseal
}

step_unseal() {
  for i in 1 2 3; do
    read -rsp "Unseal key $i/3: " k; echo
    kubectl -n openbao exec -i openbao-0 -- bao operator unseal "$k" >/dev/null
  done
  kubectl -n openbao exec openbao-0 -- bao status | grep -E "Sealed|Initialized"
}

step_vault_config() {
  : "${BAO_TOKEN:?export BAO_TOKEN=<root token> first}"
  kubectl -n openbao port-forward svc/openbao 18200:8200 >/dev/null 2>&1 &
  pf=$!; trap 'kill $pf' EXIT; sleep 2
  command -v bao >/dev/null || { echo "install the bao CLI (https://github.com/openbao/openbao/releases)"; exit 1; }
  BAO_ADDR=http://127.0.0.1:18200 KEYCLOAK_ISSUER="$KEYCLOAK_ISSUER" \
    HUB_NAMESPACE=jhub HUB_SERVICE_ACCOUNT=hub "$ROOT/vault/setup-openbao.sh"
  echo ">>> consider revoking the root token now: bao token revoke <root>"
}

step_jhub() {
  kubectl create namespace jhub --dry-run=client -o yaml | kubectl apply -f -
  kubectl -n jhub get secret jhub-crypt >/dev/null 2>&1 || \
    kubectl -n jhub create secret generic jhub-crypt --from-literal=key="$(openssl rand -hex 32)"
  if ! kubectl -n jhub get secret jhub-oidc >/dev/null 2>&1; then
    read -rsp "Keycloak client secret for 'jupyterhub': " cs; echo
    kubectl -n jhub create secret generic jhub-oidc --from-literal=client_secret="$cs"
  fi
  helm repo add jupyterhub https://hub.jupyter.org/helm-chart/ >/dev/null
  helm repo update >/dev/null
  helm upgrade --install jhub jupyterhub/jupyterhub --version "$Z2JH_VERSION" \
    -n jhub -f "$ROOT/k8s/values.yaml" --timeout 10m --wait
  kubectl -n jhub get pods,svc
}

case "${1:-}" in
  k3s) step_k3s ;; images) step_images ;; openbao) step_openbao ;;
  openbao-init) step_openbao_init ;; unseal) step_unseal ;;
  vault-config) step_vault_config ;; jhub) step_jhub ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
