#!/bin/bash
set -euo pipefail
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
