# Google Workspace MCP Integration — Design Spec

**Date:** 2026-04-11  
**Status:** Approved  
**Scope:** Wire both Hermes bot instances (dee, tracy) to Google Workspace MCP servers already running on totoro

---

## Problem

Neither `hermes-dee` nor `hermes-tracy` has access to Gmail or Google Calendar. The infrastructure is almost entirely pre-built on totoro; the only work is activating Tracy's workspace service and wiring both bots to it via config.

---

## Architecture

Each Hermes bot container connects to a dedicated `@dguido/google-workspace-mcp` instance on the totoro host via the Docker bridge (`172.17.0.1`). Each instance is pre-authorized with its owner's Google OAuth tokens (refresh token stored on disk, auto-renewed).

```
hermes-dee container   →  172.17.0.1:3102/mcp  (google-workspace-mcp.service, Dee's account)
hermes-tracy container →  172.17.0.1:3202/mcp  (google-workspace-mcp-tracy.service, Tracy's account)
```

The services are stdio MCP servers wrapped with `mcp-proxy` to expose StreamableHTTP. No auth header is required — the services are bound to the host and only reachable via the Docker bridge.

---

## Services Inventory

### State before this change

| Service | Port | State | Action |
|---|---|---|---|
| `google-workspace-mcp.service` (Dee) | 3102 | running | wire into Hermes |
| `google-workspace-mcp-tracy.service` (Tracy) | 3202 | inactive | start + enable |
| `gmail-mcp.service` (Dee) | 3101 | running | disable (redundant) |
| `gmail-mcp-tracy.service` (Tracy) | 3201 | running | disable (redundant) |
| `google-calendar-mcp.service` (Dee) | 3100 | inactive | disable (redundant) |
| `google-calendar-mcp-tracy.service` (Tracy) | 3200 | inactive | disable (redundant) |

### OAuth token coverage

Both workspace instances are authorized with full scopes:
- `mail.google.com`, `gmail.modify`, `gmail.settings.basic`
- `calendar`
- `drive`, `drive.file`, `drive.readonly`
- `documents`, `spreadsheets`, `presentations`, `contacts`

Tracy's tokens were generated on 2026-04-11 via local `google-workspace-mcp auth` on her Mac and deployed to `/home/dewoller/.config/google-workspace-mcp-tracy/tokens.json`.

---

## Changes Required

### 1. `deploy/config-dee.yaml`

Add under `mcp_servers`:

```yaml
  workspace:
    url: "http://172.17.0.1:3102/mcp"
```

### 2. `deploy/config-tracy.yaml`

Add under `mcp_servers`:

```yaml
  workspace:
    url: "http://172.17.0.1:3202/mcp"
```

### 3. Totoro service management

```bash
# Activate Tracy's workspace MCP
sudo systemctl enable --now google-workspace-mcp-tracy.service
```

### 4. Deploy Hermes

Run the existing deploy pipeline to push updated configs to totoro containers.

---

## Tools Exposed

`@dguido/google-workspace-mcp v3.4.4` — all tools enabled, no filtering:

- **Gmail**: list, read, search, send, draft, label, trash emails
- **Calendar**: list calendars, list/get/create/update/delete events, free/busy
- **Drive**: list, read, search, upload, download files
- **Docs / Sheets / Slides**: read and edit documents
- **Contacts**: list, search, read contacts

---

## Error Handling

- Token expiry: handled automatically by `@dguido/google-workspace-mcp` (refresh token flow)
- Service crash: systemd `Restart=always` with 5s backoff
- Hermes reconnection: `mcp_tool.py` exponential backoff, 5 retries per server

---

## Testing

1. On totoro: verify `google-workspace-mcp-tracy.service` is active: `systemctl status google-workspace-mcp-tracy`
2. On totoro: verify HTTP endpoint responds: `curl -s http://localhost:3202/mcp` (expect SSE initialize response)
3. Deploy hermes-dee and hermes-tracy
4. Confirm workspace tools registered in container logs: `docker logs hermes-dee | grep workspace` and `docker logs hermes-tracy | grep workspace`
5. Smoke test: ask each bot to read its own most recent email
6. Smoke test: ask each bot to list today's calendar events
7. Only after smoke tests pass — decommission redundant services on totoro:
   ```bash
   sudo systemctl disable --now gmail-mcp.service
   sudo systemctl disable --now gmail-mcp-tracy.service
   sudo systemctl disable --now google-calendar-mcp.service
   sudo systemctl disable --now google-calendar-mcp-tracy.service
   ```

---

## Out of Scope

- Business account workspace MCP (`google-workspace-mcp-business.service`, port 3302) — separate concern
- Tool filtering / read-only mode — not required
- Auth token rotation policy — managed by Google's OAuth2 refresh mechanism
