#!/bin/sh
# vault-fetch init container: Keycloak access token -> OpenBao -> tmpfs files.
# Env: VAULT_ADDR, VAULT_JWT (user's access token, set by the Hub per spawn),
#      JUPYTERHUB_USER, OUT (default /run/user-secrets), VAULT_FETCH_REQUIRED (default false)
set -u
OUT="${OUT:-/run/user-secrets}"
U="${JUPYTERHUB_USER:?}"
umask 077
mkdir -p "$OUT/ssh" "$OUT/docker" "$OUT/helm/registry"

fail() {
  echo "vault-fetch: $*" >&2
  echo "$*" > "$OUT/.error"
  if [ "${VAULT_FETCH_REQUIRED:-false}" = "true" ]; then exit 1; fi
  exit 0   # fail open: the server starts without credentials, the terminal shows a notice
}

[ -n "${VAULT_JWT:-}" ] || fail "no access token in auth_state (log out and in again)"
BAO_TOKEN=$(bao write -field=token auth/jwt/login role=jhub-user jwt="$VAULT_JWT" 2>"$OUT/.login.err") \
  || fail "OpenBao login failed: $(head -c 300 "$OUT/.login.err")"
rm -f "$OUT/.login.err"
export BAO_TOKEN
unset VAULT_JWT

# get <kind> <field> <dest>: missing secret or field = not configured, skip
get() {
  if bao kv get -mount=secret -field="$2" "users/$U/$1" > "$3.tmp" 2>/dev/null && [ -s "$3.tmp" ]; then
    mv "$3.tmp" "$3"; echo "vault-fetch: $1/$2 -> $3"
  else
    rm -f "$3.tmp"
  fi
}
get git      credentials      "$OUT/git-credentials"
get registry docker_config    "$OUT/docker/config.json"
get helm     repositories     "$OUT/helm/repositories.yaml"
get helm     registry_config  "$OUT/helm/registry/config.json"
get ssh      private_key      "$OUT/ssh/id_ed25519"
get ssh      public_key       "$OUT/ssh/id_ed25519.pub"
get ssh      known_hosts      "$OUT/ssh/known_hosts"

bao token revoke -self >/dev/null 2>&1 || true
date -u +%FT%TZ > "$OUT/.fetched"
chmod -R go-rwx "$OUT" 2>/dev/null || true
