#!/usr/bin/env bash
# Deploy bcl_log/ to uConsole over Tailscale SSH.
#
# Usage:
#   ./apps/sdr-receiver/bcl_log/scripts/deploy_uconsole.sh
#
# Override defaults via env vars:
#   UCONSOLE_USER=osprey74 UCONSOLE_HOST=100.85.21.75 \
#   REMOTE_DIR=/home/osprey74/bcl_log ./scripts/deploy_uconsole.sh

set -euo pipefail

UCONSOLE_USER="${UCONSOLE_USER:-osprey74}"
UCONSOLE_HOST="${UCONSOLE_HOST:-100.85.21.75}"
REMOTE_DIR="${REMOTE_DIR:-/home/${UCONSOLE_USER}/bcl_log}"

HERE="$(cd "$(dirname "$0")/.." && pwd)"

echo "→ Syncing ${HERE}/  →  ${UCONSOLE_USER}@${UCONSOLE_HOST}:${REMOTE_DIR}/"
rsync -avz --delete \
    --exclude '__pycache__' \
    --exclude '.pytest_cache' \
    --exclude '*.pyc' \
    --exclude '.venv' \
    "${HERE}/" \
    "${UCONSOLE_USER}@${UCONSOLE_HOST}:${REMOTE_DIR}/"

echo "→ Installing Python deps (--user)"
ssh "${UCONSOLE_USER}@${UCONSOLE_HOST}" \
    "cd ${REMOTE_DIR} && python3 -m pip install --user -r requirements.txt"

echo
echo "Done. To run on uConsole:"
echo "    ssh ${UCONSOLE_USER}@${UCONSOLE_HOST}"
echo "    cd ${REMOTE_DIR}"
echo "    python3 -m bcl_log new"
