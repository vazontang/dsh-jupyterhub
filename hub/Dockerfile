# Hub image = Z2JH hub + the DSH settings service / spawn hook
# Build:  docker build -t jhub-dsh:poc hub/
FROM quay.io/jupyterhub/k8s-hub:4.4.4
COPY --chown=root:root dsh_settings /opt/dsh-hub/dsh_settings
ENV PYTHONPATH=/opt/dsh-hub
