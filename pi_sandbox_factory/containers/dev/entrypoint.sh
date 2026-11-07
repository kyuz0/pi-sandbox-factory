#!/bin/bash
set -euo pipefail
rm -f /tmp/pi-sandbox-factory-ready
python3 /usr/local/lib/sandbox-bootstrap.py
socat TCP-LISTEN:19431,bind=127.0.0.1,reuseaddr,fork UNIX-CONNECT:/run/inference/proxy.sock &
inference_pid=$!
if [ "${SANDBOX_NETWORK_MODE:-allowlist}" = unrestricted ]; then
    sleep infinity &
else
    socat TCP-LISTEN:3128,bind=127.0.0.1,reuseaddr,fork UNIX-CONNECT:/run/egress/proxy.sock &
fi
network_pid=$!
trap 'kill "$inference_pid" "$network_pid" 2>/dev/null || true; wait || true' EXIT
trap 'exit 0' TERM INT
touch /tmp/pi-sandbox-factory-ready
wait -n "$inference_pid" "$network_pid"
exit 1
