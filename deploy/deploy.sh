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

# Step 2: Build container image
echo "--- Building container image ---"
ssh "${HOST}" "cd ${CODE_DIR} && docker build -f deploy/Dockerfile.gateway -t hermes-gateway:latest ."

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
    ssh "${HOST}" "sudo systemctl restart ${svc} && sleep 5 && systemctl is-active ${svc}"
}

case "${INSTANCE}" in
    dee)   restart_instance dee ;;
    tracy) restart_instance tracy ;;
    both)  restart_instance dee; restart_instance tracy ;;
    nutrition-bot)
      echo "--- Restarting hermes-nutrition-bot ---"
      ssh "${HOST}" "cd ${CODE_DIR} && docker compose -f deploy/docker-compose.yaml up -d --no-deps hermes-nutrition-bot"
      ;;
    *)     echo "Unknown instance: ${INSTANCE}. Use: dee, tracy, both, or nutrition-bot"; exit 1 ;;
esac

echo ""
echo "=== Deploy complete ==="
echo "  Logs: ssh ${HOST} 'docker logs -f hermes-dee'"
echo "  Logs: ssh ${HOST} 'docker logs -f hermes-tracy'"
echo "  Logs: ssh ${HOST} 'docker logs -f hermes-nutrition-bot'"
