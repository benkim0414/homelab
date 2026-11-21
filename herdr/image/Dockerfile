FROM debian:13.4@sha256:e2d08da6f42ef4b09b165d55528a12727aeed8240dc9edf888e3ec07e10ef9da
ARG TARGETARCH
LABEL org.opencontainers.image.source="https://github.com/benkim0414/homelab"
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl openssh-server python3 tini libstdc++6 procps \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && groupadd -g 10000 herdr \
    && useradd -u 10000 -g 10000 -d /data/home -s /bin/bash herdr \
    && usermod -p '*' herdr
# Both clients are pinned together, including upstream SHA256; no runtime downloads.
COPY releases.json install_releases.py /usr/local/share/herdr/
RUN python3 /usr/local/share/herdr/install_releases.py \
      --pins /usr/local/share/herdr/releases.json --arch "$TARGETARCH" \
      --destination /usr/local/libexec \
    && ln -s /usr/local/libexec/herdr-core /usr/local/bin/herdr-core \
    && ln -s /usr/local/libexec/herdr-core /usr/local/bin/hc
RUN set -eu; case "$TARGETARCH" in \
      amd64) kubectl_sha=33bc88a24c3b09cf55bfd59e6ca977881b61fc3f25ab65bc80c65b430248648e ;; \
      arm64) kubectl_sha=88fc1aca8fd0c1b44fe379f67c39bd6858bdfc50241dc55775f84d0f5b31da3a ;; \
      *) exit 1 ;; esac; \
    curl -fL --retry 3 https://dl.k8s.io/release/v1.36.5/bin/linux/$TARGETARCH/kubectl -o /usr/local/bin/kubectl; \
    printf '%s  %s\n' "$kubectl_sha" /usr/local/bin/kubectl | sha256sum -c -; \
    chmod 0755 /usr/local/bin/kubectl
COPY herdr.sh /usr/local/bin/herdr
COPY hermes.py /usr/local/bin/hermes
COPY openclaw.py /usr/local/bin/openclaw
COPY supervise.py healthcheck.py managed_clients.py core_health.py /usr/local/libexec/
COPY config.toml /etc/herdr-default.toml
COPY sshd_config /etc/ssh/sshd_config
RUN chmod 0755 /usr/local/bin/herdr /usr/local/bin/hermes /usr/local/bin/openclaw
ENV HOME=/data/home SHELL=/bin/bash LANG=C.UTF-8
EXPOSE 2222
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/bin/python3", "-B", "/usr/local/libexec/supervise.py"]
