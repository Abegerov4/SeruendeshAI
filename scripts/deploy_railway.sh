#!/usr/bin/env bash
# Deploy the latest commit of branch `ayat` to Railway (project "seruendesh", service "seruendesh").
#   make deploy            # or: bash scripts/deploy_railway.sh [commit-sha]
# Needs the Railway CLI logged in (`railway login`). Railway builds the root Dockerfile (railway.json).
set -euo pipefail
SERVICE_ID=8788ad01-3666-40e1-911e-5ed84b054629
ENV_ID=2fbee4b6-afb7-4909-a207-e48b8f919ef5
URL=https://seruendesh-production.up.railway.app

git fetch -q origin ayat
SHA=${1:-$(git rev-parse origin/ayat)}
echo "→ deploying ayat@${SHA:0:8} to Railway"
DEP=$(railway api "mutation { serviceInstanceDeployV2(serviceId: \"$SERVICE_ID\", environmentId: \"$ENV_ID\", commitSha: \"$SHA\") }" 2>/dev/null \
      | grep -o '"serviceInstanceDeployV2": "[^"]*"' | cut -d'"' -f4)
[ -n "$DEP" ] || { echo "deploy request failed"; exit 1; }
echo "  deployment $DEP"
while :; do
  # a network blip while polling is not a failed deploy: retry on the next tick
  ST=$(railway api "{ deployment(id: \"$DEP\") { status } }" 2>/dev/null | grep -o '"status": "[A-Z_]*"' | cut -d'"' -f4 || true)
  echo "  $(date +%T) $ST"
  case "$ST" in SUCCESS) break ;; FAILED|CRASHED|REMOVED) echo "  see: railway logs --build"; exit 1 ;; esac
  sleep 15
done
curl -s -m 30 "$URL/api/health"; echo
