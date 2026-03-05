# HEARTBEAT.md
# Fires every 12h from gateway start. Keep this ultra-lean.
# Detailed health checks run via the 9AM/9PM cron job instead.

## On each heartbeat:

1. **BB ping** — Fetch the BB password and ping. Run as two steps:
   ```bash
   export OP_SERVICE_ACCOUNT_TOKEN=$(cat ~/.openclaw/.env-token)
   BB_PASS=$(op read "op://OpenClaw/BlueBubbles Password/password")
   curl -sf "http://localhost:1234/api/v1/ping?password=${BB_PASS}"
   ```
   If the curl fails (non-200 or connection refused), message Dylan: "BlueBubbles is down."

That's it. Everything else runs via the health-check cron job.
