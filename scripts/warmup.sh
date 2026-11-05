#!/usr/bin/env bash
# Load every model the talk uses and keep it in memory, so no act pays a cold start.
# Run it 5 minutes before going on stage. kev:4b needs ~20 s the first time.
set -euo pipefail

BASE="${TYPESAFE_BASE_URL:-http://localhost:11435}"

for model in laya laya:typed-decisions kev:0.8b kev:4b; do
  printf "%-22s" "$model"
  curl -s --noproxy '*' -m 120 "$BASE/api/decide" \
    -d "{\"model\": \"$model\", \"keep_alive\": -1}" >/dev/null && echo loaded
done

ollaya ps
