#!/usr/bin/env bash
# One-time setup: install Python deps and pull the Ollaya models used in the talk.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --locked

for model in laya:en laya:multilingual laya:typed-decisions kev:0.8b kev:4b; do
  ollaya pull "$model"
done

# Act 3 replays from a committed 300-row sample. Only needed for live labelling:
#   uv run act3_nhtsa/fetch_data.py
