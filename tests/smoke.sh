#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TMP_ENV="${TMPDIR:-/tmp}/agent-route-kit-agent-input.env"
TMP_BUILD="${TMPDIR:-/tmp}/agent-route-kit-build"

cd "$ROOT"

cp agent-input.example.env "$TMP_ENV"
rm -rf "$TMP_BUILD"

python3 tools/render-config.py --env "$TMP_ENV" --out "$TMP_BUILD"
python3 -m json.tool "$TMP_BUILD/sing-box/config.json" >/dev/null
python3 -m json.tool "$TMP_BUILD/claude-code/settings.json" >/dev/null
python3 -m json.tool agent-manifest.json >/dev/null
test -s "$TMP_BUILD/mihomo/config.yaml"

# Backward-compatibility test: ensure rendering succeeds when Reality is disabled and no port hopping is configured
TMP_LEGACY_ENV="${TMPDIR:-/tmp}/agent-route-kit-legacy-input.env"
TMP_LEGACY_BUILD="${TMPDIR:-/tmp}/agent-route-kit-legacy-build"
grep -v "^ENABLE_REALITY\|^REALITY_\|^HY2_PORTS" "$TMP_ENV" > "$TMP_LEGACY_ENV"
python3 tools/render-config.py --env "$TMP_LEGACY_ENV" --out "$TMP_LEGACY_BUILD"
python3 -m json.tool "$TMP_LEGACY_BUILD/sing-box/config.json" >/dev/null
test -s "$TMP_LEGACY_BUILD/mihomo/config.yaml"
rm -rf "$TMP_LEGACY_ENV" "$TMP_LEGACY_BUILD"

bash -n tools/net
bash -n tools/diagnose
bash -n scripts/check-prereqs.sh
bash -n scripts/install-local-macos.sh
bash -n scripts/deploy-relay.sh
python3 -m py_compile tools/render-config.py
python3 -m py_compile dashboard/server.py
test -s dashboard/index.html

AGENT_ROUTE_KIT_DASHBOARD_PORT=18765 python3 dashboard/server.py >/tmp/agent-route-kit-dashboard.out 2>/tmp/agent-route-kit-dashboard.err &
dashboard_pid=$!
cleanup_dashboard() {
  kill "$dashboard_pid" >/dev/null 2>&1 || true
  wait "$dashboard_pid" 2>/dev/null || true
}
trap cleanup_dashboard EXIT
for _ in 1 2 3 4 5; do
  if curl -fsS http://127.0.0.1:18765/ >/tmp/agent-route-kit-dashboard.html 2>/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS -X POST http://127.0.0.1:18765/api/status >/tmp/agent-route-kit-dashboard-status.json
python3 -m json.tool /tmp/agent-route-kit-dashboard-status.json >/dev/null
test -s /tmp/agent-route-kit-dashboard.html

if rg -n -g '!tests/smoke.sh' "BEGIN (RSA |OPENSSH |EC |)PRIVATE KEY|https?://[^[:space:]/]+:[^[:space:]@]+@|/Users/[^[:space:]]+" .; then
  echo "generic secret/privacy scan failed" >&2
  exit 1
fi

echo "smoke-ok"
