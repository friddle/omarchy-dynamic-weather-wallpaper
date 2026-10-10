#!/usr/bin/env bash
# 便捷启动: ./run.sh serve | once --apply | init | status | daemon
set -euo pipefail
cd "$(dirname "$0")"
exec python3 -m weatherwall "$@"
