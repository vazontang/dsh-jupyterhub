# Login shells (web terminal): show where credentials come from.
if [ -d /run/user-secrets ] && [ -z "$DSH_SECRETS_NOTICE_SHOWN" ]; then
  export DSH_SECRETS_NOTICE_SHOWN=1
  [ -f /run/user-secrets/.fetched ] || echo "[dsh] /run/user-secrets is empty: set credentials in the Hub 'DSH 設定' page, then restart your server."
fi
