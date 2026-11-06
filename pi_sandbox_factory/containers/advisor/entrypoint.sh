#!/bin/bash
set -euo pipefail
umask 077
mkdir -p "$HOME/.local/share/keyrings" "$CODEX_HOME" /run/advisor /run/advisor-bus
chmod 700 /run/advisor /run/advisor-bus
rm -f /run/advisor-bus/bus
# A container restart has terminated every previous advisor process.
# Interrupted ledger entries remain unresolved until /advisor recover.
rm -f "$HOME/.pi/agent/advisor/active.lock"
dbus-daemon --session --address="$DBUS_SESSION_BUS_ADDRESS" --nofork --nopidfile &
bus_pid=$!
# This keyring belongs only to this companion; no host session bus is mounted.
# The private volume is the protection boundary, not an unattended password.
printf '\n' | gnome-keyring-daemon --unlock --components=secrets --control-directory=/run/advisor-bus/keyring
socat TCP-LISTEN:3128,bind=127.0.0.1,reuseaddr,fork UNIX-CONNECT:/run/egress/proxy.sock &
relay_pid=$!
node /opt/advisor/scripts/server.mjs &
server_pid=$!
trap 'kill "$server_pid" "$relay_pid" "$bus_pid" 2>/dev/null || true; wait || true' EXIT
trap 'exit 0' TERM INT
wait -n "$server_pid" "$relay_pid" "$bus_pid"
exit 1
