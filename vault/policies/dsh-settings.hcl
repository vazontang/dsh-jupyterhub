# Settings service (Hub): write / replace / delete per-user secrets, never read them.
path "secret/data/users/*" {
  capabilities = ["create", "update"]
}
path "secret/metadata/users/*" {
  capabilities = ["delete"]
}
