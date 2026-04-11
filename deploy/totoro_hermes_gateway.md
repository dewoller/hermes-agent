# Totoro Hermes Gateway

This runbook is the source of truth for the Hermes gateway deployment on Totoro. It covers Dee and Tracy only. It does not own the nutrition-service database, import pipeline, or service runtime.

Verified against the live Totoro host on April 10, 2026:

- `hermes-dee.service` is active
- `hermes-tracy.service` is active
- Docker containers `hermes-dee` and `hermes-tracy` are running from `hermes-gateway:latest`
- the repo checkout on Totoro is `/tank/services/active_services/hermes`

## Layout

The install has four layers:

1. the git checkout lives at `/tank/services/active_services/hermes`
2. Docker builds `hermes-gateway:latest` from `deploy/Dockerfile.gateway`
3. systemd owns the long-running services: `hermes-dee.service` and `hermes-tracy.service`
4. each instance gets its own `HERMES_HOME` bind mount:
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

1. clones or updates the repo at `/tank/services/active_services/hermes`
2. creates instance homes for `hermes-dee` and `hermes-tracy`
3. creates `.venv` in the repo checkout and installs `.[messaging,mcp,cli,cron]`
4. installs WhatsApp bridge Node dependencies
5. pulls the Docker sandbox image `nikolaik/python-nodejs:python3.12-nodejs22`
6. creates SOPS-encrypted `.env.sops` templates for each instance
7. installs and enables the systemd unit files

After the script finishes, complete the manual steps on Totoro:

```bash
ssh totoro_ts

cd /tank/services/active_services/hermes-dee
sops .env.sops

cd /tank/services/active_services/hermes-tracy
sops .env.sops

HERMES_HOME=/tank/services/active_services/hermes-dee \
  /tank/services/active_services/hermes/.venv/bin/hermes login --provider openai-codex

HERMES_HOME=/tank/services/active_services/hermes-tracy \
  /tank/services/active_services/hermes/.venv/bin/hermes login --provider openai-codex

sudo systemctl start hermes-dee
sudo systemctl start hermes-tracy
```

## Runtime Files

Code checkout:

- `/tank/services/active_services/hermes`

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

External nutrition-service dependency:

- `NUTRITION_SERVICE_BASE_URL` points Hermes at the standalone nutrition API
- Hermes does not own the nutrition database or import pipeline

## New Telegram Bot Token

Telegram bot tokens belong in the Hermes gateway instance secret, not in the standalone nutrition service.

To provision a new bot token for a Hermes-backed nutrition bot:

1. Talk to `@BotFather` and create the new bot with `/newbot`.
2. Copy the token into the target Hermes instance `.env.sops` as `TELEGRAM_BOT_TOKEN=...`.
3. Add `TELEGRAM_ALLOWED_USERS=...` for the accounts allowed to use that bot.
4. If that bot should call the standalone nutrition service from a Totoro Docker container, set `NUTRITION_SERVICE_BASE_URL=http://172.17.0.1:8781`.
5. Restart the corresponding Hermes systemd unit after saving the secret.

The nutrition service itself should never store or read Telegram bot tokens.

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
- secrets do not live in the repo checkout. The unit files decrypt `.env.sops` into `/run/secrets/hermes-*` before container start.
- the repo checkout is the build source. The running gateway process lives inside the Docker image built from that checkout.
- `hermes-dee` runs as `1000:1004`, not `root`, so writes into the mounted Obsidian repo land as `dewoller` while Dee still keeps access to `/data` and the mounted `.env` file.
- `hermes-tracy` does not get the Obsidian mount.

## Migration Note

If `hermes-dee` previously ran as `root`, its existing `HERMES_HOME` may contain root-owned files such as `config.yaml`, `auth.json`, cache files, or hook directories. The first non-root start will fail until ownership is fixed.

One-time repair on Totoro:

```bash
/usr/bin/ssh totoro_ts 'sudo chown -R 1000:1004 /tank/services/active_services/hermes-dee'
sudo systemctl restart hermes-dee
```
