#!/bin/bash
set -euo pipefail
rm -f /tmp/local-ai-sandbox-ready
python3 /usr/local/lib/sandbox-bootstrap.py
touch /tmp/local-ai-sandbox-ready
if [ "${SANDBOX_NETWORK_MODE:-allowlist}" = unrestricted ]; then
    exec sleep infinity
fi
exec socat TCP-LISTEN:3128,bind=127.0.0.1,reuseaddr,fork UNIX-CONNECT:/run/egress/proxy.sock
