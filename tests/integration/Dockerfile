ARG BASE=debian:bookworm-slim
FROM ${BASE}
ENV container=docker
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d \
    && chmod +x /usr/sbin/policy-rc.d \
    && apt-get update -qq \
    && DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
       systemd systemd-sysv dbus ca-certificates curl caddy python3 python3-flask python3-waitress \
    && rm -f /usr/sbin/policy-rc.d \
    && rm -rf /var/lib/apt/lists/* \
    && touch /etc/caddy-manager-integration-only
STOPSIGNAL SIGRTMIN+3
CMD ["/sbin/init"]
