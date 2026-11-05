# Per-user image: JupyterLab + DSH web + jupyter-mcp-server
# Build:  docker build -t dsh-notebook:poc notebook/
FROM quay.io/jupyter/minimal-notebook:python-3.12

ARG NODE_VERSION=24.11.0
ARG DSH_VERSION=0.2.2-rc.1
ARG HELM_VERSION=v3.19.0
# keep in step with the Hub chart (Z2JH 4.4.4 ships JupyterHub 5.5.4)
ARG JUPYTERHUB_VERSION=5.5.4

USER root
RUN apt-get update && apt-get install -y --no-install-recommends \
        git openssh-client curl ca-certificates xz-utils less vim-tiny jq \
    && rm -rf /var/lib/apt/lists/*

# Node 24+ (DSH requires node >= 24.9)
RUN curl -fsSL https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-x64.tar.xz \
      | tar -xJ -C /usr/local --strip-components=1 \
    && node -v

# DSH (pinned: developer preview, breaking changes expected)
RUN npm install -g @deepseek-ai/dsh@${DSH_VERSION} && npm cache clean --force

# helm client (registry / chart repo creds come from /run/user-secrets)
RUN curl -fsSL https://get.helm.sh/helm-${HELM_VERSION}-linux-amd64.tar.gz \
      | tar -xz -C /usr/local/bin --strip-components=1 linux-amd64/helm

RUN pip install --no-cache-dir \
        "jupyterhub==${JUPYTERHUB_VERSION}" \
        jupyter-server-proxy==4.6.0 \
        jupyter-mcp-server==2.2.5 \
        jupyter-collaboration==5.0.4

# glue
COPY dsh-launch /usr/local/bin/dsh-launch
COPY dsh_open.py /opt/conda/lib/python3.12/site-packages/dsh_open.py
COPY jupyter_server_config.py /etc/jupyter/jupyter_server_config.py
COPY dsh.svg /etc/dsh/dsh.svg
COPY skills/ /opt/dsh/skills/
COPY gitconfig /etc/gitconfig
COPY ssh_config /etc/ssh/ssh_config.d/50-user-secrets.conf
COPY user-env.sh /etc/profile.d/50-user-secrets.sh
RUN chmod 0755 /usr/local/bin/dsh-launch \
    && chmod -R a+rX /opt/dsh /etc/dsh /etc/jupyter /etc/gitconfig

ENV DSH_BUNDLED_SKILL_DIR=/opt/dsh/skills \
    DOCKER_CONFIG=/run/user-secrets/docker \
    HELM_REPOSITORY_CONFIG=/run/user-secrets/helm/repositories.yaml \
    HELM_REGISTRY_CONFIG=/run/user-secrets/helm/registry/config.json

USER ${NB_UID}
WORKDIR /home/${NB_USER}
