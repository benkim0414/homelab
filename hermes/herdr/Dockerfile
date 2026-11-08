FROM debian:13.4@sha256:e2d08da6f42ef4b09b165d55528a12727aeed8240dc9edf888e3ec07e10ef9da
ARG TARGETARCH
LABEL org.opencontainers.image.source="https://github.com/benkim0414/homelab"
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl openssh-server python3 tini libstdc++6 procps \
    && rm -rf /var/lib/apt/lists/* /etc/ssh/ssh_host_* \
    && groupadd -g 10000 herdr \
    && useradd -u 10000 -g 10000 -d /data/home -s /bin/bash herdr \
    && usermod -p '*' herdr
# Upstream release checksums are reviewed and fixed here; no runtime downloads.
RUN set -eu; case "$TARGETARCH" in \
      amd64) herdr_arch=x86_64; herdr_sha=14d9e8bc8b4a9e0118d77c32266f76d461f09b40342eb23752960bd89f59929d; kubectl_sha=33bc88a24c3b09cf55bfd59e6ca977881b61fc3f25ab65bc80c65b430248648e ;; \
      arm64) herdr_arch=aarch64; herdr_sha=17d7536f2da50859523680ef279dffcac8e4a235f4e46fe8da6c2ec44141897c; kubectl_sha=88fc1aca8fd0c1b44fe379f67c39bd6858bdfc50241dc55775f84d0f5b31da3a ;; \
      *) exit 1 ;; esac; \
    mkdir -p /usr/local/libexec; \
    curl -fL --retry 3 https://github.com/herdrdev/herdr/releases/download/v0.9.5/herdr-linux-$herdr_arch -o /usr/local/libexec/herdr; \
    printf '%s  %s\n' "$herdr_sha" /usr/local/libexec/herdr | sha256sum -c -; \
    curl -fL --retry 3 https://dl.k8s.io/release/v1.36.5/bin/linux/$TARGETARCH/kubectl -o /usr/local/bin/kubectl; \
    printf '%s  %s\n' "$kubectl_sha" /usr/local/bin/kubectl | sha256sum -c -; \
    chmod 0755 /usr/local/libexec/herdr /usr/local/bin/kubectl
COPY herdr.sh /usr/local/bin/herdr
COPY hermes-cluster.py /usr/local/bin/hermes-cluster
COPY supervise.py healthcheck.py /usr/local/libexec/
COPY config.toml /etc/herdr-default.toml
COPY sshd_config /etc/ssh/sshd_config
RUN chmod 0755 /usr/local/bin/herdr /usr/local/bin/hermes-cluster
ENV HOME=/data/home SHELL=/bin/bash LANG=C.UTF-8
EXPOSE 2222
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/bin/python3", "-B", "/usr/local/libexec/supervise.py"]
