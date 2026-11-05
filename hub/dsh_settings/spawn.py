"""Hub-side spawn hook: inject DSH settings as env and add the vault-fetch init container.

values.yaml:  hub.extraConfig.dsh: |
    from dsh_settings.spawn import pre_spawn_hook
    c.Spawner.pre_spawn_hook = pre_spawn_hook
"""
import os

from .store import load_settings, spawn_env

VAULT_ADDR = os.environ.get("DSH_VAULT_ADDR", "http://openbao.openbao.svc:8200")
FETCH_IMAGE = os.environ.get("DSH_VAULT_FETCH_IMAGE", "vault-fetch:poc")
SECRETS_VOLUME = "user-secrets"   # emptyDir medium=Memory, defined in singleuser.storage.extraVolumes


async def pre_spawn_hook(spawner):
    user = spawner.user
    settings = await load_settings(user.name)
    spawner.environment.update(spawn_env(settings))

    auth_state = await user.get_auth_state() or {}
    access_token = auth_state.get("access_token", "")

    if hasattr(spawner, "init_containers"):  # KubeSpawner
        # The user's Keycloak access token only appears in this init container's env.
        # It is short-lived (refresh_pre_spawn renews it just before this hook).
        spawner.init_containers = [c for c in spawner.init_containers if c.get("name") != "vault-fetch"] + [{
            "name": "vault-fetch",
            "image": FETCH_IMAGE,
            "imagePullPolicy": "IfNotPresent",
            "env": [
                {"name": "VAULT_ADDR", "value": VAULT_ADDR},
                {"name": "VAULT_JWT", "value": access_token},
                {"name": "JUPYTERHUB_USER", "value": user.name},
                {"name": "OUT", "value": "/run/user-secrets"},
            ],
            "volumeMounts": [{"name": SECRETS_VOLUME, "mountPath": "/run/user-secrets"}],
            "securityContext": {
                "runAsUser": 1000, "runAsGroup": 100, "runAsNonRoot": True,
                "allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                "capabilities": {"drop": ["ALL"]},
            },
            "resources": {"limits": {"cpu": "200m", "memory": "64Mi"}},
        }]
    else:  # local test spawner: same contract, handed over as env
        spawner.environment["DSH_TEST_VAULT_JWT"] = access_token
