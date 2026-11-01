#!/bin/bash
set -euo pipefail
case "${1:-}" in
  codex) exec advisor-codex -c 'cli_auth_credentials_store="file"' login --device-auth ;;
  agy) export SSH_CONNECTION='127.0.0.1 0 127.0.0.1 0'; exec agy ;;
  *) echo 'Choose codex or agy.' >&2; exit 2 ;;
esac
