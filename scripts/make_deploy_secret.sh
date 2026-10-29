#!/usr/bin/env bash
# Create the Modal secret for a shared deployment (modal_app.py) from the keys in .env, with an access code and low caps of its own.
# Only the four provider keys are taken from .env; everything else is set here, so the shared copy cannot spend more than these caps.
# Usage: scripts/make_deploy_secret.sh            (prints the access code at the end)
# Override any value in the environment, e.g.: BUDGET_HARD_CAP_USD=10 PAID_CALLS_UNTIL=2026-11-03T12:00:00Z scripts/make_deploy_secret.sh
set -euo pipefail
cd "$(dirname "$0")/.."

CODE="${ACCESS_CODE:-$(openssl rand -hex 5)}"
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT

grep -E '^(MODEL_API_KEY|BASETEN_API_KEY|MODAL_ENDPOINT_URL|MODAL_ENDPOINT_TOKEN)=' .env > "$TMP"
cat >> "$TMP" <<EOF
REASONING_PROVIDER=baseten
ACCESS_CODE=$CODE
PAID_CALLS_UNTIL=${PAID_CALLS_UNTIL:-2026-11-03T18:00:00Z}
BUDGET_HARD_CAP_USD=${BUDGET_HARD_CAP_USD:-15}
BASETEN_BUDGET_CAP_USD=${BASETEN_BUDGET_CAP_USD:-5}
MODAL_BUDGET_CAP_USD=${MODAL_BUDGET_CAP_USD:-5}
RUN_CAP_USD=${RUN_CAP_USD:-1}
RUN_LIMIT_PER_IP_HOUR=${RUN_LIMIT_PER_IP_HOUR:-10}
RUN_LIMIT_PER_DAY=${RUN_LIMIT_PER_DAY:-80}
MAX_CONCURRENT_RUNS=${MAX_CONCURRENT_RUNS:-2}
EOF

uvx --from modal modal secret create orbitroute-keys --from-dotenv "$TMP" --force
echo
echo "Secret orbitroute-keys created. Access code for your friends: $CODE"
echo "Live calls stop on ${PAID_CALLS_UNTIL:-2026-11-03T18:00:00Z}; caps for this copy: Meta \$${BUDGET_HARD_CAP_USD:-15}, Baseten \$${BASETEN_BUDGET_CAP_USD:-5}, Modal \$${MODAL_BUDGET_CAP_USD:-5}."
