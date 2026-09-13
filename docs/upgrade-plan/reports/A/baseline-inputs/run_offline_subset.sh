#!/usr/bin/env bash
# Thin wrapper. Run from repo root. Does not modify skillforge/ or product tests.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../../../../.." && pwd)"
cd "$ROOT"
mapfile -t NODEIDS < <(grep -v '^[[:space:]]*$' "$(dirname "$0")/offline-nodeids.txt")
python3 -m pytest -v --tb=short --no-header "${NODEIDS[@]}"
