#!/usr/bin/env bash
#
# Bird of the Day — container healthcheck.
#
# Three checks in order:
#   1. feed.xml exists on the volume
#   2. feed.xml was modified within the last 36 hours (12h grace after
#      the daily 07:00 UTC cron — catches stuck or failing schedules)
#   3. nginx is actually serving feed.xml on localhost:8080
#
# Returns non-zero on any failure. The Docker HEALTHCHECK then marks the
# container as `unhealthy`, surfacing the problem to the orchestrator.

set -eu

DATA_DIR="${BOTD_STATE_DIR:-/var/lib/botd}"

# 1) feed.xml exists
if [ ! -f "${DATA_DIR}/feed.xml" ]; then
    echo "healthcheck: feed.xml missing at ${DATA_DIR}" >&2
    exit 1
fi

# 2) modified within the last 36h (2160 minutes)
if ! find "${DATA_DIR}/feed.xml" -mmin -2160 -print -quit | grep -q .; then
    echo "healthcheck: feed.xml is older than 36h" >&2
    exit 1
fi

# 3) nginx is responding
if ! curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8080/feed.xml; then
    echo "healthcheck: nginx is not serving /feed.xml on 8080" >&2
    exit 1
fi

exit 0
