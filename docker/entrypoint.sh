#!/usr/bin/env bash
#
# Bird of the Day — container entrypoint.
#
# Sequence:
#   1. Ensure the state directory exists and is writable.
#   2. If feed.xml is missing (cold start on a fresh volume), run the
#      generator synchronously so the first request gets a real page.
#   3. Launch supercronic in the background for the daily refresh.
#   4. exec into the CMD (typically nginx) so it becomes PID 1's child
#      under tini, with proper signal forwarding.

set -euo pipefail

DATA_DIR="${BOTD_STATE_DIR:-/var/lib/botd}"
APP_DIR="/app"
CRONTAB="/etc/supercronic/crontab"
PLACEHOLDER="${APP_DIR}/placeholder.html"

log() {
    printf '[entrypoint] %s\n' "$*" >&2
}

# 1) Ensure the state dir is in shape. The volume mount may be empty on
#    first run, so we create the cache subdir explicitly.
mkdir -p "${DATA_DIR}/cache"

# If no config.json exists, bootstrap from the example shipped with the image.
if [ ! -f "${APP_DIR}/data/config.json" ]; then
    log "no config.json found, copying config.example.json"
    cp "${APP_DIR}/data/config.example.json" "${APP_DIR}/data/config.json"
fi

# 2) Cold-start: synchronously run the generator if there's no feed.xml.
if [ ! -f "${DATA_DIR}/feed.xml" ]; then
    log "cold start: no feed.xml on volume, running generator synchronously"
    if (cd "${APP_DIR}" && /opt/venv/bin/python -m scripts.generate); then
        log "cold-start generation succeeded"
    else
        log "WARN: cold-start generation failed; serving placeholder until next cron run"
        # Friendly fallback so the first visitor doesn't hit a 503.
        cp "${PLACEHOLDER}" "${DATA_DIR}/index.html" 2>/dev/null || true
    fi
else
    log "feed.xml present on volume, skipping cold-start generation"
fi

# 3) supercronic in the background. tini will reap it on shutdown.
log "starting supercronic with ${CRONTAB}"
cd "${APP_DIR}"
supercronic -quiet=false "${CRONTAB}" &
SUPERCRONIC_PID=$!
log "supercronic running as pid ${SUPERCRONIC_PID}"

# Belt-and-braces signal handler. tini already forwards SIGTERM/SIGINT to
# this script, but trapping here means a `kill` of supercronic on shutdown
# is explicit and visible in the logs.
_shutdown() {
    log "shutdown signal received, stopping supercronic (pid ${SUPERCRONIC_PID})"
    kill -TERM "${SUPERCRONIC_PID}" 2>/dev/null || true
    wait "${SUPERCRONIC_PID}" 2>/dev/null || true
}
trap _shutdown TERM INT

# 4) Hand off to nginx (or whatever CMD was passed).
log "exec: $*"
exec "$@"
