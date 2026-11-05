#!/usr/bin/env bash
# One-time OpenBao setup for the DSH PoC. Run after init + unseal with a root/admin token:
#   export BAO_ADDR=http://127.0.0.1:8200 BAO_TOKEN=<root token>
#   KEYCLOAK_ISSUER=https://sso.example.com/realms/corp ./setup-openbao.sh
# For a local test without Keycloak, set JWT_VALIDATION_PUBKEY_FILE instead of KEYCLOAK_ISSUER.
set -euo pipefail
cd "$(dirname "$0")"
: "${BAO_ADDR:?}" "${BAO_TOKEN:?}"
JWT_AUDIENCE="${JWT_AUDIENCE:-jupyterhub}"
HUB_NAMESPACE="${HUB_NAMESPACE:-jhub}"
HUB_SERVICE_ACCOUNT="${HUB_SERVICE_ACCOUNT:-hub}"

bao secrets list -format=json | grep -q '"secret/"' || bao secrets enable -path=secret kv-v2

# --- users: JWT (Keycloak access token) -> read own secrets ---
bao auth list -format=json | grep -q '"jwt/"' || bao auth enable jwt
if [ -n "${KEYCLOAK_ISSUER:-}" ]; then
  bao write auth/jwt/config oidc_discovery_url="$KEYCLOAK_ISSUER" bound_issuer="$KEYCLOAK_ISSUER"
else
  : "${JWT_VALIDATION_PUBKEY_FILE:?set KEYCLOAK_ISSUER or JWT_VALIDATION_PUBKEY_FILE}"
  bao write auth/jwt/config jwt_validation_pubkeys=@"$JWT_VALIDATION_PUBKEY_FILE" bound_issuer="${JWT_ISSUER:-local-test}"
fi
ACCESSOR=$(bao auth list -format=json | python3 -c 'import json,sys; print(json.load(sys.stdin)["jwt/"]["accessor"])')
sed "s/__JWT_ACCESSOR__/$ACCESSOR/" policies/jhub-user.hcl.tmpl | bao policy write jhub-user -
bao write auth/jwt/role/jhub-user \
  role_type=jwt user_claim=preferred_username bound_audiences="$JWT_AUDIENCE" \
  token_policies=jhub-user token_ttl=2m token_max_ttl=5m token_num_uses=0

# --- settings service: Kubernetes service account -> write-only ---
bao policy write dsh-settings policies/dsh-settings.hcl
if [ "${SKIP_K8S_AUTH:-}" != "1" ]; then
  bao auth list -format=json | grep -q '"kubernetes/"' || bao auth enable kubernetes
  # OpenBao runs in the same k3s cluster: it uses its own pod's SA to review tokens
  bao write auth/kubernetes/config kubernetes_host="https://kubernetes.default.svc:443"
  bao write auth/kubernetes/role/dsh-settings \
    bound_service_account_names="$HUB_SERVICE_ACCOUNT" \
    bound_service_account_namespaces="$HUB_NAMESPACE" \
    token_policies=dsh-settings token_ttl=15m
fi
echo "OpenBao configured: kv-v2 at secret/, jwt role jhub-user (accessor $ACCESSOR), policy dsh-settings"
