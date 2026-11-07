# Agent Deployment Contract

This document is the automation contract. An AI agent should be able to deploy the project after a human fills `agent-input.env`.

## Required Human Input

The human fills:

- `RELAY_SSH_TARGET`
- `AI_RELAY_HOST`
- `AI_RELAY_PORT`
- `HY2_PASSWORD`
- `HY2_SNI`
- `STABLE_EGRESS_HTTP_HOST`
- `STABLE_EGRESS_HTTP_PORT`
- `STABLE_EGRESS_HTTP_USERNAME`
- `STABLE_EGRESS_HTTP_PASSWORD`
- `AI_DOMAINS`
- `CORPORATE_DOMAINS` when internal routing is needed
- `DIRECT_DOMAINS` when extra local/direct routing is needed

Optional inputs:
- `HY2_PORTS`: Port hopping range (e.g. `20000-40000`) to avoid ISP UDP QoS throttling.
- `ENABLE_REALITY`: Set to `true` to enable TCP VLESS-Reality as secondary fallback.
- `REALITY_PORT`, `REALITY_UUID`, `REALITY_SNI`, `REALITY_PRIVATE_KEY`, `REALITY_PUBLIC_KEY`, `REALITY_SHORT_ID`: Keys generated on the relay via:
  `sing-box generate reality-keypair && sing-box generate uuid && openssl rand -hex 8`

The human should not edit templates directly.

## Agent Procedure

1. Validate that `agent-input.env` exists and is not committed.
2. Check prerequisites and input renderability:

   ```bash
   bash scripts/check-prereqs.sh agent-input.env
   ```

3. Render configs:

   ```bash
   python3 tools/render-config.py --env agent-input.env --out build
   ```

4. Inspect generated metadata:

   ```bash
   python3 -m json.tool build/deployment-metadata.json
   ```

5. Install local config:

   ```bash
   bash scripts/install-local-macos.sh build
   ```

   This validates the generated mihomo config, installs a launchd service, and starts or restarts the local router.

6. Deploy relay config:

   ```bash
   bash scripts/deploy-relay.sh build
   ```

   This uploads the rendered sing-box config, creates a self-signed certificate if needed, validates config when `sing-box` is available, and restarts the relay service.

7. Switch to the normal profile:

   ```bash
   bash tools/net on
   ```

8. Validate:

   ```bash
   bash tools/net status
   bash tools/diagnose
   make smoke
   ```

## Completion Evidence

Deployment is not complete until the agent can show:

- `build/mihomo/config.yaml` exists.
- `build/sing-box/config.json` exists.
- The relay service reports `active`.
- Local router API responds on `127.0.0.1`.
- Local launchd service exists on macOS when `install-local-macos.sh` is used.
- AI provider domains match the `ai-route` group in local router logs or API evidence.
- Corporate/internal domains, if configured, resolve through the native resolver and route `DIRECT`.
- General unmatched traffic follows the selected `MODE`.

## Failure Handling

- If rendering fails, ask only for the missing input keys.
- If SSH fails, ask only for relay access details or network reachability.
- If relay service restart fails, collect `systemctl status` and `journalctl -u` excerpts.
- If local routing fails, run `tools/diagnose` and inspect bounded router logs.

Do not request broad manual intervention. Convert every failure into a missing input, failed command, or explicit environment prerequisite.
