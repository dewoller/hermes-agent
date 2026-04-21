#!/usr/bin/env bash
# One-time setup for hermes-agent on totoro.
# Run from your LOCAL machine: ./deploy/setup-totoro.sh
set -euo pipefail

HOST="${1:-totoro_ts}"
CODE_DIR="/tank/services/active_services/hermes-agent"
REPO_URL="https://github.com/realmindsai/hermes-agent.git"

# SOPS age recipients (same as nanoclaw)
AGE_R0="age1nugp23x9246u5l6dl4mmkzm5en5ty885em875grclryv8n7ux9psgg9tjz"
AGE_R1="age16kgy3rpakglw7kr0nqv0h3qff0p99d0kalyxw9rc59w2dkaz6gwq3ghlq5"
AGE_R2="age1dmlnp2875aharwptr9pt5egqf982jdyt2wqdwy6s9t56g4gmup4qv0splj"

echo "=== Hermes Agent Setup on ${HOST} ==="
echo ""
echo "Code:       ${CODE_DIR}"
echo "Dee home:   ${CODE_DIR}-dee"
echo "Tracy home: ${CODE_DIR}-tracy"
echo ""

# Step 1: Clone repo on totoro
echo "--- Step 1: Clone repo ---"
ssh "${HOST}" bash -s <<REMOTE_SCRIPT
set -euo pipefail

if [ -d "${CODE_DIR}/.git" ]; then
    echo "Repo already exists at ${CODE_DIR}, pulling latest..."
    cd "${CODE_DIR}" && git pull --ff-only
else
    echo "Cloning ${REPO_URL} to ${CODE_DIR}..."
    git clone "${REPO_URL}" "${CODE_DIR}"
fi
REMOTE_SCRIPT

# Step 2: Create HERMES_HOME directories
echo ""
echo "--- Step 2: Create instance directories ---"
ssh "${HOST}" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
CODE_DIR="/tank/services/active_services/hermes-agent"

for INSTANCE in hermes-dee hermes-tracy hermes-nutrition-bot; do
    DIR="/tank/services/active_services/${INSTANCE}"
    echo "Setting up ${DIR}..."
    mkdir -p "${DIR}"/{logs,sessions,memories,skills,cache,cron}

    # Symlink config from deploy/
    # Map instance name to config filename (nutrition-bot -> nutrition)
    CONFIG_SUFFIX="${INSTANCE#hermes-}"
    [ "${CONFIG_SUFFIX}" = "nutrition-bot" ] && CONFIG_SUFFIX="nutrition"
    CONFIG_SRC="${CODE_DIR}/deploy/config-${CONFIG_SUFFIX}.yaml"
    if [ -f "${CONFIG_SRC}" ]; then
        ln -sf "${CONFIG_SRC}" "${DIR}/config.yaml"
        echo "  config.yaml -> ${CONFIG_SRC}"
    fi
done
REMOTE_SCRIPT

# Step 3: Create Python venv and install
echo ""
echo "--- Step 3: Install Python dependencies ---"
ssh "${HOST}" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
CODE_DIR="/tank/services/active_services/hermes-agent"
cd "${CODE_DIR}"

# Use uv if available, fall back to pip
if command -v uv &>/dev/null; then
    echo "Using uv..."
    if [ ! -d ".venv" ]; then
        uv venv .venv --python 3.12
    fi
    source .venv/bin/activate
    uv pip install -e ".[messaging,mcp,cli,cron]"
else
    echo "uv not found, using pip..."
    python3.12 -m venv .venv
    source .venv/bin/activate
    pip install -e ".[messaging,mcp,cli,cron]"
fi

echo ""
echo "Installed hermes at: $(which hermes)"
hermes --version 2>/dev/null || echo "(version check skipped)"
REMOTE_SCRIPT

# Step 4: Install WhatsApp bridge dependencies
echo ""
echo "--- Step 4: WhatsApp bridge ---"
ssh "${HOST}" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
CODE_DIR="/tank/services/active_services/hermes-agent"
cd "${CODE_DIR}/scripts/whatsapp-bridge"
if [ -f "package.json" ]; then
    npm install
    echo "WhatsApp bridge dependencies installed."
else
    echo "No whatsapp-bridge/package.json found, skipping."
fi
REMOTE_SCRIPT

# Step 5: Pull Docker image for sandboxed execution
echo ""
echo "--- Step 5: Docker sandbox image ---"
ssh "${HOST}" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
echo "Pulling Docker sandbox image..."
docker pull nikolaik/python-nodejs:python3.12-nodejs22
echo "Docker image ready."
REMOTE_SCRIPT

# Step 6: Create SOPS-encrypted .env files (templates)
echo ""
echo "--- Step 6: SOPS .env templates ---"
ssh "${HOST}" bash -s "${AGE_R0}" "${AGE_R1}" "${AGE_R2}" <<'REMOTE_SCRIPT'
set -euo pipefail
AGE_R0="$1"; AGE_R1="$2"; AGE_R2="$3"

for INSTANCE in hermes-dee hermes-tracy; do
    DIR="/tank/services/active_services/${INSTANCE}"
    SOPS_FILE="${DIR}/.env.sops"

    if [ -f "${SOPS_FILE}" ]; then
        echo "${INSTANCE}: .env.sops already exists, skipping."
        continue
    fi

    # Create a placeholder .env to encrypt
    SUFFIX="${INSTANCE#hermes-}"
    TEMPLATE="${DIR}/.env.template"
    cat > "${TEMPLATE}" <<EOF
# Hermes Agent - ${SUFFIX}
TELEGRAM_BOT_TOKEN=CHANGEME
TELEGRAM_ALLOWED_USERS=CHANGEME
WHATSAPP_ENABLED=false
WHATSAPP_ALLOWED_USERS=CHANGEME
EOF

    if command -v sops &>/dev/null; then
        echo "${INSTANCE}: Encrypting .env with SOPS..."
        sops --encrypt \
            --age "${AGE_R0},${AGE_R1},${AGE_R2}" \
            --input-type dotenv \
            --output-type dotenv \
            "${TEMPLATE}" > "${SOPS_FILE}"
        rm -f "${TEMPLATE}"
        echo "  Created ${SOPS_FILE}"
    else
        echo "${INSTANCE}: SOPS not found. Left template at ${TEMPLATE}"
        echo "  Encrypt manually: sops --encrypt --age '${AGE_R0},${AGE_R1},${AGE_R2}' --input-type dotenv --output-type dotenv ${TEMPLATE} > ${SOPS_FILE}"
    fi
done
REMOTE_SCRIPT

# Step 7: Install systemd services
echo ""
echo "--- Step 7: Systemd services ---"
scp "$(dirname "$0")/hermes-dee.service" "${HOST}:/tmp/hermes-dee.service"
scp "$(dirname "$0")/hermes-tracy.service" "${HOST}:/tmp/hermes-tracy.service"
ssh "${HOST}" bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
sudo cp /tmp/hermes-dee.service /etc/systemd/system/hermes-dee.service
sudo cp /tmp/hermes-tracy.service /etc/systemd/system/hermes-tracy.service
sudo systemctl daemon-reload
sudo systemctl enable hermes-dee hermes-tracy
echo "Services installed and enabled (not started yet)."
echo ""
echo "  sudo systemctl start hermes-dee"
echo "  sudo systemctl start hermes-tracy"
REMOTE_SCRIPT

echo ""
echo "=== Setup complete ==="
echo ""
echo "Next steps:"
echo "  1. SSH to ${HOST} and edit secrets:"
echo "     ssh ${HOST}"
echo "     cd /tank/services/active_services/hermes-dee"
echo "     sops .env.sops    # Add real TELEGRAM_BOT_TOKEN, etc."
echo ""
echo "  2. Login to OpenAI Codex (for each instance):"
echo "     HERMES_HOME=/tank/services/active_services/hermes-dee \\"
echo "       /tank/services/active_services/hermes-agent/.venv/bin/hermes login --provider openai-codex"
echo ""
echo "  3. Start services:"
echo "     sudo systemctl start hermes-dee"
echo "     sudo systemctl start hermes-tracy"
echo ""
echo "  4. hermes-nutrition-bot (Docker Compose, no systemd):"
echo "     REMINDER: SOPS-encrypt .env using deploy/env-nutrition.example template"
echo "               Install to /run/secrets/hermes-nutrition-bot/.env on ${HOST}"
echo "     deploy/deploy.sh ${HOST} nutrition-bot"
echo "     REMINDER: After first start: docker exec hermes-nutrition-bot hermes login --provider openai-codex"
