#!/usr/bin/env bash
# Deploy hermes-agent updates to totoro.
# Usage: ./deploy/deploy.sh [host] [instance]
# Examples:
#   ./deploy/deploy.sh                    # deploy both to totoro_ts
#   ./deploy/deploy.sh totoro_ts dee      # deploy only dee
#   ./deploy/deploy.sh totoro_ts tracy    # deploy only tracy
set -euo pipefail

HOST="${1:-totoro_ts}"
INSTANCE="${2:-both}"
CODE_DIR="/tank/services/active_services/hermes"

echo "=== Deploying Hermes Agent to ${HOST} ==="

# Step 1: Push code
echo "--- Pulling latest code ---"
ssh "${HOST}" "cd ${CODE_DIR} && git pull --ff-only"

# Step 2: Update dependencies if pyproject.toml changed
echo "--- Checking dependencies ---"
ssh "${HOST}" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
cd /tank/services/active_services/hermes
source .venv/bin/activate
uv pip install -e ".[messaging,mcp,cli,cron]" --quiet 2>/dev/null || pip install -e ".[messaging,mcp,cli,cron]" --quiet
REMOTE_SCRIPT

# Step 3: Update systemd units
echo "--- Updating systemd services ---"
scp "$(dirname "$0")/hermes-dee.service" "${HOST}:/tmp/hermes-dee.service"
scp "$(dirname "$0")/hermes-tracy.service" "${HOST}:/tmp/hermes-tracy.service"
ssh "${HOST}" bash -s <<'REMOTE_SCRIPT'
sudo cp /tmp/hermes-dee.service /etc/systemd/system/hermes-dee.service
sudo cp /tmp/hermes-tracy.service /etc/systemd/system/hermes-tracy.service
sudo systemctl daemon-reload
REMOTE_SCRIPT

# Step 4: Restart requested instances
restart_instance() {
    local svc="hermes-$1"
    echo "--- Restarting ${svc} ---"
    ssh "${HOST}" "sudo systemctl restart ${svc} && sleep 2 && systemctl is-active ${svc}"
}

case "${INSTANCE}" in
    dee)   restart_instance dee ;;
    tracy) restart_instance tracy ;;
    both)  restart_instance dee; restart_instance tracy ;;
    *)     echo "Unknown instance: ${INSTANCE}. Use: dee, tracy, or both"; exit 1 ;;
esac

echo ""
echo "=== Deploy complete ==="
echo "  Logs: ssh ${HOST} 'journalctl -u hermes-dee -f'"
echo "  Logs: ssh ${HOST} 'journalctl -u hermes-tracy -f'"
