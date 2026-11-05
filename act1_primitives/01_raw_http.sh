#!/usr/bin/env bash
# Act 1, step 1: the whole API in one request. No SDK, no Python.
# Ollaya listens on 11435 and speaks the same wire format as Jev.
set -euo pipefail

BASE="${TYPESAFE_BASE_URL:-http://localhost:11435}"

curl -s --noproxy '*' "$BASE/v1/models" -H "Authorization: Bearer local" | python3 -m json.tool
echo

curl -s --noproxy '*' "$BASE/v1/systemone" \
  -H "Authorization: Bearer local" \
  -d '{
  "model": "laya:en",
  "state": "Can I get an invoice for last month?",
  "questions": {
    "intent": {
      "type": "choice",
      "instructions": "What does the customer want?",
      "criteria": {
        "invoice": "Needs an invoice or receipt",
        "refund": "Wants money back",
        "other": "Anything else"
      }
    }
  }
}' | python3 -m json.tool
