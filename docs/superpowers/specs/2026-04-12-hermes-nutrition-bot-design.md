# Hermes Nutrition Bot — Design Spec

**Date:** 2026-04-12
**Status:** Approved

---

## Overview

A dedicated Hermes gateway instance (`hermes-nutrition-bot`) that handles Telegram DM-based meal logging. Hermes is the conversational brain: it does first-pass photo recognition via the Codex vision model and recalls meal patterns from memory. The standalone `nutrition-service` (at `http://172.17.0.1:8781`) owns all nutrient truth, candidate resolution, pending state, meal logs, and learned corrections.

---

## Key Decisions

| Decision | Choice |
|---|---|
| Deployment | Docker alongside Dee/Tracy |
| Chat scope | Telegram DM only |
| Bot behaviour | Nutrition-only (`HERMES_NUTRITION_BOT=1`) |
| Photo perception | Codex model via agent loop (vision + memory) |
| Learned recognition | nutrition-service canonical |
| Pending candidate state | nutrition-service owns it; Hermes stateless between turns |
| MCP servers | None |
| nutrition_state.py | Not needed |

---

## Session Key

`session_key` throughout this spec is the value returned by the existing `build_session_key()` function for the Telegram DM source. For Telegram private chats, `build_session_key()` uses `chat_id`, which is numerically equal to the sender's `user_id`. Do not derive `session_key` manually — call `build_session_key(source)` so that any future changes to key derivation are inherited automatically.

---

## Architecture

```
Telegram DM
    │
    ▼
gateway/run.py  ── HERMES_NUTRITION_BOT=1 gate ──► Normal agent loop (skipped)
    │
    ├─ photo msg ──────────────────────────────────────────────────┐
    │                                                               │
    │                                                               ▼
    │                                              Agent loop (_run_agent via runner)
    │                                              Codex model sees photo + memory
    │                                              Outputs structured JSON observations
    │                                                               │
    ├─ nc: callback ──► nutrition_bridge.handle_selection()         │
    │                                                               │
    └─ plain text ──► get_pending() check                          │
                           │                                        │
                      pending? ──yes──► nutrition_bridge.correct()  │
                           │                                        ▼
                      no ──► "Send me a photo"   nutrition_client.analyze(session_id, observations)
                                                               │
                                              http://172.17.0.1:8781/api/nutrition/v1/
                                              (owns candidates, pending state, meal log, learning)
                                                               │
                                              ◄── {candidate_set_id, candidates[{id, label, ...}]}
                                                               │
                                              Inline keyboard rendered to user
```

---

## Components

### `gateway/platforms/base.py` — MessageEvent extension

Add `callback_data: Optional[str] = None` to the `MessageEvent` dataclass. This field is currently absent. It is populated by the Telegram adapter fall-through for unknown callback prefixes and read by `run.py` to route `nc:` callbacks. Without this field, `event.callback_data` raises `AttributeError`.

---

### `gateway/nutrition_client.py` — thin HTTP client

Four calls against nutrition-service. No business logic.

```python
analyze(session_id: str, observations: list[dict]) -> dict
    # POST /api/nutrition/v1/analyze
    # observations: [{name, brand, barcode, quantity_g, confidence}]
    # returns: {
    #   candidate_set_id: str,
    #   candidates: [{id: str, label: str, calories_kcal: int, protein_g: float, ...}]
    # }
    # candidate.id is the value used in nc:{set_id}:{candidate.id} callback data

select(session_id: str, candidate_set_id: str, candidate_id: str) -> dict
    # POST /api/nutrition/v1/select
    # returns: {logged: bool}

correct(session_id: str, candidate_set_id: str, correction_text: str) -> dict
    # POST /api/nutrition/v1/correct
    # candidate_set_id comes from get_pending() — the bridge threads it through
    # returns: {logged: bool}

get_pending(session_id: str) -> dict | None
    # GET /api/nutrition/v1/pending/{session_id}
    # returns: {candidate_set_id: str, candidates: [{id, label, ...}]} or None on 404
```

Base URL from `NUTRITION_SERVICE_BASE_URL` env var (default: `http://172.17.0.1:8781`).

---

### `gateway/nutrition_bridge.py` — orchestration

Three public async methods. `runner` is the `GatewayRunner` instance (`self` from `run.py`).

**Calling the agent loop for photo analysis:**
`_run_agent` has no system-prompt-override parameter. Pass the nutrition SOUL as `context_prompt`, which appends it to the existing context. The SOUL prompt begins with a clear instruction, so stacking on the default system prompt is acceptable — the model will follow the nutrition-specific instruction when the event contains a photo and no other conversation context.

**JSON extraction from agent output:**
The model may wrap its output in markdown fences (` ```json ... ``` `) even with strict prompting. Use a regex to strip them robustly before parsing:
```python
import re
cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", output.strip())
observations = json.loads(cleaned)
```

```python
handle_photo_event(event, session_key, runner, adapter)
    # 1. Call runner._run_agent with required positional args:
    #      message      = event.text or "" (the user's photo caption, if any)
    #      context_prompt = NUTRITION_SOUL
    #      history      = []  (no prior conversation history; each meal is a fresh turn)
    #      source       = event.source
    #      session_id   = session_key  (use session_key as session_id for the agent)
    #    The agent sees the photo (from event.media_urls) and user memory.
    # 2. Strip markdown fences from agent output using regex, then json.loads()
    # 3. Call nutrition_client.analyze(session_key, observations)
    # 4. Render inline keyboard to Telegram with candidates
    #    Button callback_data format: nc:{candidate_set_id}:{candidate.id}
    #    Button label: candidate.label
    # On nutrition-service unreachable: send "Nutrition service unavailable, try again shortly."
    # On malformed JSON after stripping: send "Couldn't read that photo, try again."

handle_candidate_selection(callback_data, session_key, adapter)
    # 1. Parse nc:{set_id}:{candidate_id} from callback_data
    #    On malformed data: log and return (no reply — treat as stale button)
    # 2. Call nutrition_client.select(session_key, set_id, candidate_id)
    # 3. On success: send "Logged!"
    # 4. On server error: send "Nutrition service unavailable, try again shortly."

handle_correction(text, session_key, adapter)
    # 1. Call nutrition_client.get_pending(session_key)
    #    Returns {candidate_set_id, candidates[]} or None
    # 2. If pending:
    #      call nutrition_client.correct(session_key, pending["candidate_set_id"], text)
    #      On success: send "Updated!"
    #      On server error: send "Nutrition service unavailable, try again shortly."
    # 3. If none pending: send "Send me a photo of your meal."
```

---

### Nutrition SOUL prompt

Embedded as a module-level constant in `nutrition_bridge.py`. Passed as `context_prompt` to `_run_agent`.

> You are a nutrition logging assistant. When given a food photo, output ONLY a JSON array of observations: `[{name, brand, barcode, quantity_g, confidence}]`. Recall from memory any past meals matching what you see. No narrative. No questions. JSON only.

---

### `gateway/run.py` — nutrition gate

Inserted after update-prompt check, before agent dispatch. Access platform and chat type via `event.source`. Mirror the existing `build_session_key` call pattern at line 777 — pass config-driven kwargs so future config changes are inherited:

```python
if _nutrition_bot_enabled():           # HERMES_NUTRITION_BOT == "1"
    source = event.source
    if source.platform != Platform.TELEGRAM or source.chat_type != "dm":
        return                         # drop silently
    config = getattr(self, "config", None)
    session_key = build_session_key(
        source,
        group_sessions_per_user=getattr(config, "group_sessions_per_user", True),
        thread_sessions_per_user=getattr(config, "thread_sessions_per_user", False),
    )
    if event.callback_data and event.callback_data.startswith("nc:"):
        return await bridge.handle_candidate_selection(
            event.callback_data, session_key, adapter)
    if event.media_urls:               # photo
        return await bridge.handle_photo_event(
            event, session_key, self, adapter)
    return await bridge.handle_correction(
        event.text, session_key, adapter)
```

`self` is passed as `runner` so the bridge can call `self._run_agent(...)`.

---

### `gateway/platforms/telegram.py`

The existing `_handle_callback_query` method at line 1440-1442 uses a **negative guard**:

```python
# --- Update prompt callbacks ---
if not data.startswith("update_prompt:"):
    return
```

This drops every unrecognised callback before any fall-through can be added. The fix is a one-line refactor: convert the negative guard to a positive `if` block and add a fall-through `else`:

```python
# --- Update prompt callbacks ---
if data.startswith("update_prompt:"):
    answer = data.split(":", 1)[1]  # "y" or "n"
    await query.answer(text=f"Sent '{answer}' to the update process.")
    # ... rest of existing update_prompt handling unchanged ...
    return

# --- Unknown callbacks (nc: and future prefixes) ---
await query.answer()   # required: clears Telegram's loading spinner
# Build a MessageEvent with callback_data populated and dispatch to run.py
event = self._build_callback_event(query, data)  # helper to construct the event
await self.handle_message(event)   # use handle_message(), not _message_handler directly
                                   # handle_message() provides session dedup, interrupt
                                   # support, and background-task spawning
```

`_build_callback_event` is a new private helper that constructs a `MessageEvent` with `callback_data=data` set (using the same source/session fields as text messages).

---

## Message Flows

### Photo DM

1. User sends meal photo
2. Telegram adapter downloads photo → populates `event.media_urls`
3. `run.py` → nutrition gate → `handle_photo_event(event, session_key, self, adapter)`
4. Bridge calls `runner._run_agent(context_prompt=NUTRITION_SOUL, ...)` — Codex sees photo, recalls meal patterns, outputs JSON
5. Bridge strips markdown fences (regex), JSON-parses observations
6. Bridge → `nutrition_client.analyze(session_key, observations)`
7. nutrition-service returns `{candidate_set_id, candidates[{id, label, ...}]}`; stores pending state
8. Bridge renders inline keyboard: one button per candidate, `nc:{candidate_set_id}:{candidate.id}` as callback data, `candidate.label` as button text

### Button tap (candidate selection)

1. User taps inline button
2. Telegram adapter fall-through → `query.answer()` → `_build_callback_event()` → `event.callback_data = "nc:set123:cand456"` → `self.handle_message(event)`
3. `run.py` → nutrition gate → `handle_candidate_selection("nc:set123:cand456", session_key, adapter)`
4. Bridge → `nutrition_client.select(session_key, "set123", "cand456")`
5. nutrition-service logs meal, clears pending state
6. Bridge sends "Logged!" confirmation

### Plain text DM

1. User sends text
2. `run.py` → nutrition gate → `handle_correction(text, session_key, adapter)`
3. Bridge → `nutrition_client.get_pending(session_key)` → `{candidate_set_id, candidates[]}` or `None`
4. **Pending:** `nutrition_client.correct(session_key, candidate_set_id, text)` → send "Updated!"
5. **No pending:** send "Send me a photo of your meal."
6. **Server error:** send "Nutrition service unavailable, try again shortly."

---

## Deploy / Ops

### `deploy/docker-compose.yaml` — third service

The existing `hermes-dee` and `hermes-tracy` services use `restart: "no"` because systemd units manage their lifecycle. `hermes-nutrition-bot` has no systemd unit, so `restart: unless-stopped` is intentional and correct for this service.

The existing `deploy.sh` invokes `docker compose` from `CODE_DIR` on the host. Use the same absolute-path pattern as the existing services for the config seed mount:

```yaml
hermes-nutrition-bot:
  container_name: hermes-nutrition-bot
  image: hermes-gateway:latest
  build:
    context: ..
    dockerfile: deploy/Dockerfile.gateway
  user: "1000:1004"
  environment:
    - HERMES_HOME=/data
  volumes:
    - /tank/services/active_services/hermes-nutrition-bot:/data
    - /tank/services/active_services/hermes/deploy/config-nutrition.yaml:/opt/config-seed.yaml:ro
    - /run/secrets/hermes-nutrition-bot/.env:/data/.env:ro
  restart: unless-stopped    # intentional: no systemd unit for this service
  logging:
    driver: json-file
    options:
      max-size: "10m"
      max-file: "3"
```

### `deploy/config-nutrition.yaml` — narrow seed config

Memory config matches the `dee`/`tracy` pattern (`mode: "local"` only — no separate backend key required):

```yaml
model:
  default: "gpt-5.4"
  provider: "openai-codex"

memory:
  mode: "local"

# No terminal, no STT, no MCP servers, no Obsidian mount
```

### `deploy/env-nutrition.example`

```
TELEGRAM_BOT_TOKEN=<new BotFather token>
TELEGRAM_ALLOWED_USERS=<telegram user id>
NUTRITION_SERVICE_BASE_URL=http://172.17.0.1:8781
HERMES_NUTRITION_BOT=1
```

### `deploy/deploy.sh` — nutrition-bot target

The existing build step (line 22) runs `docker build -t hermes-gateway:latest` before the case statement — it executes for all targets including `nutrition-bot`, so the image is always fresh.

Note: lines 24-32 (systemd unit SCP and `daemon-reload`) also run unconditionally before the case statement. For a `nutrition-bot` deploy this is benign — the `.service` files for dee/tracy are re-copied but the nutrition-bot has no systemd unit, so daemon-reload has no effect on it.

Add a `nutrition-bot` case that SSHes to the host and restarts via `docker compose` (no systemd unit):

```bash
nutrition-bot)
  ssh "${HOST}" "cd ${CODE_DIR} && docker compose -f deploy/docker-compose.yaml up -d --no-deps hermes-nutrition-bot"
  ;;
```

The existing `both` case covers `dee` and `tracy` only and remains unchanged — `nutrition-bot` is excluded from `both` as it is a separate-purpose service.

### Totoro setup (`deploy/setup-totoro.sh`)

Add a provisioning block for the new instance. Mirror the existing instance pattern, which creates the following subdirectory structure under the data directory:

```bash
DIR=/tank/services/active_services/hermes-nutrition-bot
mkdir -p "${DIR}"/{logs,sessions,memories,skills,cache,cron}
chown -R 1000:1004 "${DIR}"
# install SOPS-encrypted .env
# copy config-nutrition.yaml seed
```

The subdirectories `logs,sessions,memories,skills,cache,cron` are required — they match what the gateway expects at runtime.

### `deploy/totoro_docker_install.md`

Add a section documenting the `hermes-nutrition-bot` instance: container name, data path (`/tank/services/active_services/hermes-nutrition-bot`), required env vars (`HERMES_NUTRITION_BOT=1`, `NUTRITION_SERVICE_BASE_URL=http://172.17.0.1:8781`), deploy command (`./deploy.sh totoro_ts nutrition-bot`), Codex login requirement, and the fact that it has no MCP servers or Obsidian mount.

### Codex login (post-first-start)

After the container starts for the first time, run `hermes login --provider openai-codex` inside the container (or copy OAuth tokens from an existing instance's `HERMES_HOME`). Auth is per-`HERMES_HOME` — without this step the bot starts but all photo analysis fails immediately with an auth error.

---

## Files Added

| File | Purpose |
|---|---|
| `gateway/nutrition_client.py` | HTTP client for nutrition-service |
| `gateway/nutrition_bridge.py` | Telegram orchestration |
| `deploy/config-nutrition.yaml` | Seed config for nutrition bot instance |
| `deploy/env-nutrition.example` | Secret template |

## Files Modified

| File | Change |
|---|---|
| `gateway/platforms/base.py` | Add `callback_data: Optional[str] = None` to `MessageEvent` dataclass |
| `gateway/run.py` | Add `HERMES_NUTRITION_BOT` gate before agent dispatch |
| `gateway/platforms/telegram.py` | Refactor `update_prompt:` negative guard to positive if/else; add fall-through for unknown callbacks with `query.answer()` + `_build_callback_event()` helper |
| `deploy/docker-compose.yaml` | Add `hermes-nutrition-bot` service stanza |
| `deploy/setup-totoro.sh` | Add new instance provisioning block with full subdirectory structure |
| `deploy/deploy.sh` | Add `nutrition-bot` case using SSH + `docker compose up` |
| `deploy/totoro_docker_install.md` | Add `hermes-nutrition-bot` instance documentation section |

## Files Explicitly Not Added

| File | Reason |
|---|---|
| `gateway/nutrition_state.py` | nutrition-service owns pending state |
| `nutrition_service/client.py` | Wrong location; replaced by `gateway/nutrition_client.py` |

---

## Tests

### Directory note

`tests/gateway/` already exists. `tests/integration/` and `tests/e2e/` may need to be created — add `__init__.py` to each if missing.

### `tests/gateway/test_nutrition_client.py` — unit, httpx mock

- `analyze()` builds correct payload and parses `{candidate_set_id, candidates[{id, label}]}` response
- `get_pending()` returns `None` on 404
- `select()` / `correct()` happy path and server error cases
- Base URL defaults and env var override

### `tests/gateway/test_nutrition_bridge.py` — unit, mocked client + adapter + runner

- Photo → `_run_agent` called via runner with nutrition SOUL as `context_prompt` → regex fence strip → JSON parse → `analyze()` called → inline keyboard rendered with `nc:{set_id}:{candidate.id}` callback data
- Agent output with markdown fences (` ```json\n[...]\n``` `) parsed correctly
- `nc:set123:cand456` callback → `select()` called with correct args → "Logged!" sent
- `select()` server error → "Nutrition service unavailable" sent
- Plain text + pending → `get_pending()` returns `{candidate_set_id, ...}` → `correct()` called with that `candidate_set_id` → "Updated!" sent
- Plain text + no pending → "Send me a photo of your meal." sent
- Plain text + `correct()` server error → "Nutrition service unavailable" sent
- Malformed `nc:` callback data → logged, no reply sent

### `tests/gateway/test_nutrition_routing.py` — unit, routing contract

Tests `run.py` gate logic only (no real Telegram, no nutrition-service, no model calls):

- Photo (populated `event.media_urls`) routes to `handle_photo_event`
- `event.callback_data = "nc:..."` routes to `handle_candidate_selection`
- Plain text routes to `handle_correction`
- Non-DM message (`source.chat_type != "dm"`) dropped silently
- Non-Telegram platform dropped silently

### `tests/e2e/test_nutrition_bot_e2e.py` — full stack, real nutrition-service, real adapter

Exercises the complete path from Telegram adapter → `run.py` → bridge → real nutrition-service. No real Telegram connection — uses the adapter's internal `_message_handler` directly with constructed `MessageEvent` objects.

- Skipped if `NUTRITION_SERVICE_BASE_URL` unreachable (same session-scoped fixture as integration tests)
- Runner is mocked for agent output (no Codex call) but all other components are real
- Full photo flow: adapter receives photo event → `run.py` gate routes to bridge → bridge calls nutrition-service → inline keyboard message sent to adapter's send mock
- Full callback flow: adapter receives `nc:` callback event → gate routes to `handle_candidate_selection` → nutrition-service logs meal → "Logged!" sent
- Full correction flow: adapter receives text event with pending state in nutrition-service → gate routes to `handle_correction` → nutrition-service logs correction → "Updated!" sent
- Non-DM event: adapter receives group message → gate drops it silently

### `tests/integration/test_nutrition_gateway_flow.py` — real nutrition-service, mocked runner

- Skip uses a session-scoped pytest fixture with `pytest.skip()` at runtime (not `@pytest.mark.skipif` at collection time, which would make a network call during import). Fixture checks service reachability once per session.
- Runner is mocked to return fixed JSON observations (no Codex API call needed)
- Photo → observe → candidates → select → logged
- Photo → observe → candidates → correct (with `candidate_set_id` from `get_pending()`) → logged
- Session isolation: two `session_key` values do not share pending state

---

## Error Handling

| Scenario | Handler | User reply |
|---|---|---|
| nutrition-service unreachable (any call) | log error | "Nutrition service unavailable, try again shortly." |
| Agent loop returns malformed JSON (after fence strip) | log | "Couldn't read that photo, try again." |
| Malformed `nc:` callback data | log | (no reply — stale button press) |
| `select()` server error | log | "Nutrition service unavailable, try again shortly." |
| `correct()` server error | log | "Nutrition service unavailable, try again shortly." |
| Non-DM message in nutrition mode | log | (no reply) |
| Non-Telegram platform in nutrition mode | log | (no reply) |
