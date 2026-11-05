# vault-fetch init container: bao CLI + fetch.sh
# Build:  docker build -t vault-fetch:poc vault-fetch/
# same OpenBao version as the server chart (openbao-helm 0.30.6)
FROM quay.io/openbao/openbao:2.7.2
COPY --chmod=0755 fetch.sh /fetch.sh
USER 1000:100
ENTRYPOINT ["/fetch.sh"]
