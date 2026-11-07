#!/bin/bash
set -euo pipefail
# Podman Machine resolves this name through its host networking service.
if [[ "${SANDBOX_MODEL_HOST:-}" == host.containers.internal ]]; then
    model_address=$(getent ahostsv4 host.containers.internal | awk 'NR==1 {print $1}') || model_address=
    if [[ ! "$model_address" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
        echo 'Cannot resolve host.containers.internal; check Podman Machine host networking.' >&2
        exit 1
    fi
    printf '%s local-model.internal\n' "$model_address" >> /etc/hosts
fi
# Only this container can change the socket directory. Clients mount it read-only.
chmod 755 /run/egress
rm -f /run/egress/proxy.sock
squid -N -f /etc/squid/sandbox.conf &
squid_pid=$!
socat UNIX-LISTEN:/run/egress/proxy.sock,fork,mode=0666 TCP:127.0.0.1:3128 &
relay_pid=$!
trap 'kill "$squid_pid" "$relay_pid" 2>/dev/null || true; wait || true' EXIT
trap 'exit 0' TERM INT
# A failed component stops the gateway; it never falls back to direct access.
wait -n "$squid_pid" "$relay_pid"
exit 1
