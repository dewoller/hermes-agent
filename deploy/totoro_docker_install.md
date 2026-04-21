# Totoro Docker Install

This note documents the Hermes deployment that runs on Totoro. It is not the generic local install, and it is not the public `docker run` example from the website docs.

Verified against the live Totoro host on April 10, 2026:

- `hermes-dee.service` is active
- `hermes-tracy.service` is active
- Docker containers `hermes-dee` and `hermes-tracy` are running from `hermes-gateway:latest`
- The repo checkout on Totoro is `/tank/services/active_services/hermes-agent`

## Layout

The install has four layers:

1. The git checkout lives at `/tank/services/active_services/hermes-agent`.
2. Docker builds `hermes-gateway:latest` from `deploy/Dockerfile.gateway`.
3. systemd owns the long-running services: `hermes-dee.service` and `hermes-tracy.service`.
4. Each instance gets its own `HERMES_HOME` bind mount:
   - `/tank/services/active_services/hermes-dee`
   - `/tank/services/active_services/hermes-tracy`

Each container mounts only three things:

- `/data` -> the instance home directory
- `/data/.env` -> a decrypted secret file from `/run/secrets/hermes-*/.env`
- `/opt/config-seed.yaml` -> the git-tracked config seed from `deploy/config-*.yaml`

`hermes-dee` also mounts Dee's Obsidian git repo:

- `/tank/personal/obsidian-personal` -> `/workspace/extra/obsidian`

At container start, `deploy/entrypoint-gateway.sh`:

- creates the standard `HERMES_HOME` directories
- copies the config seed to `/data/config.yaml`
- bootstraps `SOUL.md` if missing
- syncs bundled skills
- runs `hermes gateway`

## One-Time Install

Run the setup script from the local machine:

```bash
./deploy/setup-totoro.sh totoro_ts
```

That script does the following on Totoro:

1. Clones or updates the repo at `/tank/services/active_services/hermes-agent`.
2. Creates instance homes for `hermes-dee` and `hermes-tracy`.
3. Creates `.venv` in the repo checkout and installs `.[messaging,mcp,cli,cron]`.
4. Installs WhatsApp bridge Node dependencies.
5. Pulls the Docker sandbox image `nikolaik/python-nodejs:python3.12-nodejs22`.
6. Creates SOPS-encrypted `.env.sops` templates for each instance.
7. Installs and enables the systemd unit files.

After the script finishes, complete the manual steps on Totoro:

```bash
ssh totoro_ts

cd /tank/services/active_services/hermes-dee
sops .env.sops

cd /tank/services/active_services/hermes-tracy
sops .env.sops

HERMES_HOME=/tank/services/active_services/hermes-dee \
  /tank/services/active_services/hermes-agent/.venv/bin/hermes login --provider openai-codex

HERMES_HOME=/tank/services/active_services/hermes-tracy \
  /tank/services/active_services/hermes-agent/.venv/bin/hermes login --provider openai-codex

sudo systemctl start hermes-dee
sudo systemctl start hermes-tracy
```

## Runtime Files

Code checkout:

- `/tank/services/active_services/hermes-agent`

Per-instance state:

- `/tank/services/active_services/hermes-dee`
- `/tank/services/active_services/hermes-tracy`

Decrypted runtime secrets:

- `/run/secrets/hermes-dee/.env`
- `/run/secrets/hermes-tracy/.env`

Config seeds in git:

- `deploy/config-dee.yaml`
- `deploy/config-tracy.yaml`

Mounted workspace for Dee only:

- `/tank/personal/obsidian-personal` -> `/workspace/extra/obsidian`

Inbound voice transcription for Dee:

- host service: `parakeet-stt` at `http://127.0.0.1:8770`
- container bridge target: `http://172.17.0.1:8770`
- config seed: `deploy/config-dee.yaml` sets `stt.provider: parakeet`

Logs:

- `/tank/services/active_services/hermes-dee/logs/hermes.log`
- `/tank/services/active_services/hermes-dee/logs/hermes.error.log`
- `/tank/services/active_services/hermes-tracy/logs/hermes.log`
- `/tank/services/active_services/hermes-tracy/logs/hermes.error.log`

## Deploying Updates

From the local machine:

```bash
./deploy/deploy.sh totoro_ts
```

That script:

1. pulls the latest code on Totoro
2. rebuilds `hermes-gateway:latest`
3. refreshes the systemd unit files
4. restarts `hermes-dee`, `hermes-tracy`, or both

Deploy a single instance:

```bash
./deploy/deploy.sh totoro_ts dee
./deploy/deploy.sh totoro_ts tracy
```

## Verifying The Install

Check service state:

```bash
/usr/bin/ssh totoro_ts 'sudo systemctl status hermes-dee hermes-tracy --no-pager'
```

Check containers:

```bash
/usr/bin/ssh totoro_ts 'sudo docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}" | grep hermes'
```

Tail logs:

```bash
/usr/bin/ssh totoro_ts 'docker logs -f hermes-dee'
/usr/bin/ssh totoro_ts 'docker logs -f hermes-tracy'
```

Inspect the mounted files:

```bash
/usr/bin/ssh totoro_ts 'sudo docker inspect hermes-dee --format "{{json .Mounts}}"'
/usr/bin/ssh totoro_ts 'sudo docker inspect hermes-tracy --format "{{json .Mounts}}"'
```

## Important Notes

- systemd is the process supervisor here. Do not use `hermes gateway install` on Totoro for these instances.
- Secrets do not live in the repo checkout. The unit files decrypt `.env.sops` into `/run/secrets/hermes-*` before container start.
- The repo checkout is the build source. The running gateway process lives inside the Docker image built from that checkout.
- `hermes-dee` runs as `1000:1004`, not `root`, so writes into the mounted Obsidian repo land as `dewoller` while Dee still keeps access to `/data` and the mounted `.env` file.
- `hermes-tracy` does not get the Obsidian mount.

## Migration Note

If `hermes-dee` previously ran as `root`, its existing `HERMES_HOME` may contain root-owned files such as `config.yaml`, `auth.json`, cache files, or hook directories. The first non-root start will fail until ownership is fixed.

One-time repair on Totoro:

```bash
/usr/bin/ssh totoro_ts 'sudo chown -R 1000:1004 /tank/services/active_services/hermes-dee'
sudo systemctl restart hermes-dee
```

## Current Layout Note

Dee's checked-in config now uses:

```yaml
terminal:
  cwd: "/workspace/extra/obsidian"
```

That path is backed by the writable bind mount from `/tank/personal/obsidian-personal` for `hermes-dee` only. Tracy keeps the simpler `/data`-only runtime shape.

## hermes-nutrition-bot

A dedicated Telegram DM nutrition bot — separate from Dee and Tracy, no systemd unit.

**Container:** `hermes-nutrition-bot`
**Data path:** `/tank/services/active_services/hermes-nutrition-bot`
**Config seed:** `deploy/config-nutrition.yaml` (no MCP, no STT, no Obsidian)

**Required env (SOPS-encrypted .env):**
- `TELEGRAM_BOT_TOKEN` — separate bot token from @BotFather
- `TELEGRAM_ALLOWED_USERS` — comma-separated Telegram user IDs
- `NUTRITION_SERVICE_BASE_URL=http://172.17.0.1:8781`
- `HERMES_NUTRITION_BOT=1`

**Deploy:**
```bash
./deploy/deploy.sh totoro_ts nutrition-bot
```

**First-start Codex auth (required before photo analysis works):**
```bash
docker exec -it hermes-nutrition-bot hermes login --provider openai-codex
```

**Restart:** `restart: unless-stopped` (Docker Compose manages restart — no systemd unit).
**Scope:** Telegram DMs only. No MCP servers, no general chat, no Obsidian.
