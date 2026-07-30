#!/bin/bash
set -e

# Imbi container entrypoint
# Validates required environment variables and dispatches to the
# appropriate service command.

IMBI_SERVICE="${IMBI_SERVICE:-all}"

# --------------------------------------------------------------------------
# Environment variable validation
# --------------------------------------------------------------------------

errors=""

require_var() {
    val="${!1:-}"
    if [ -z "$val" ]; then
        errors="${errors}  - $1: $2\n"
    fi
}

require_common_vars() {
    require_var IMBI_AUTH_JWT_SECRET "JWT signing secret for authentication"
}

require_api_vars() {
    require_common_vars
    require_var CLICKHOUSE_URL "ClickHouse connection URL (e.g. clickhouse+http://default:password@clickhouse:8123/imbi)"
    require_var IMBI_AUTH_ENCRYPTION_KEY "Fernet encryption key for sensitive data"
}

require_assistant_vars() {
    require_common_vars
}

require_gateway_vars() {
    require_var POSTGRES_URL "PostgreSQL connection URL (e.g. postgresql://user:pass@host/db)"
}

require_slackbot_vars() {
    require_var SLACK_APP_TOKEN "Slack app-level token for socket mode"
    require_var SLACK_BOT_TOKEN "Slack bot OAuth token"
    require_var ANTHROPIC_API_KEY "Anthropic API key (bot stays disabled without it)"
    require_var POSTGRES_URL "PostgreSQL connection URL (e.g. postgresql://user:pass@host/db)"
}

require_scheduler_vars() {
    # Postgres holds task definitions and the execution leases; ClickHouse
    # holds run history and is written on every firing.
    require_common_vars
    require_var POSTGRES_URL "PostgreSQL connection URL (e.g. postgresql://user:pass@host/db)"
    require_var CLICKHOUSE_URL "ClickHouse connection URL (e.g. clickhouse+http://default:password@clickhouse:8123/imbi)"
    # Its own service account, per ADR 0002: there is no credential store, so
    # these are the only credentials the scheduler can run a task as. Without
    # them every api-target firing resolves no principal and is skipped.
    require_var IMBI_SCHEDULER_SA_CLIENT_ID "Client id of the scheduler's service account"
    require_var IMBI_SCHEDULER_SA_CLIENT_SECRET "Client secret of the scheduler's service account"
    # imbi-api mounts its routes under the path of its *public* URL, while
    # IMBI_INTERNAL_API_URL is a bare origin. The scheduler re-derives that
    # prefix from IMBI_API_URL; unset, every api target requests a path
    # without it and 404s, turning every run into a failure.
    require_var IMBI_API_URL "imbi-api's public URL, whose path is its route prefix"
    # And the origin the prefix is joined onto. Its default (localhost:8000) is
    # only ever right in 'all' mode, where imbi-api shares the container; in
    # scheduler mode there is nothing on localhost to reach.
    require_var IMBI_INTERNAL_API_URL "In-cluster origin of imbi-api (e.g. http://imbi-api:8000)"
}

check_errors() {
    if [ -n "$errors" ]; then
        echo "ERROR: Missing required environment variables for $1:" >&2
        printf '%b' "$errors" >&2
        echo "" >&2
        echo "Set the variables above and try again." >&2
        exit 1
    fi
}

# --------------------------------------------------------------------------
# Command dispatch (check before service env validation)
# --------------------------------------------------------------------------

# If a command argument is passed (e.g. "setup"), run it directly
if [ "$1" = "setup" ]; then
    shift
    require_api_vars
    check_errors "setup"
    exec imbi-api setup "$@"
fi

# If an explicit command is passed, run it directly
if [ $# -gt 0 ]; then
    exec "$@"
fi

# --------------------------------------------------------------------------
# Service environment validation
# --------------------------------------------------------------------------

case "$IMBI_SERVICE" in
    all)
        require_common_vars
        require_var CLICKHOUSE_URL "ClickHouse connection URL (e.g. clickhouse+http://default:password@clickhouse:8123/imbi)"
        require_var IMBI_AUTH_ENCRYPTION_KEY "Fernet encryption key for sensitive data"
        require_gateway_vars
        # Slack bot is optional in 'all' mode: it auto-enables only when
        # ANTHROPIC_API_KEY and the SLACK_* tokens are present, so its vars
        # are not required here. The scheduler is optional on the same terms:
        # it needs its own service-account credentials to run anything, so
        # without them it would only skip.
        ;;
    api)
        require_api_vars
        ;;
    assistant)
        require_assistant_vars
        ;;
    gateway)
        require_gateway_vars
        ;;
    mcp)
        # No required vars currently
        ;;
    scheduler)
        require_scheduler_vars
        ;;
    slackbot)
        require_slackbot_vars
        ;;
    *)
        echo "ERROR: Unknown service '$IMBI_SERVICE'" >&2
        echo "Valid values: all, api, assistant, gateway, mcp, scheduler, slackbot" >&2
        exit 1
        ;;
esac

check_errors "service '$IMBI_SERVICE'"

# --------------------------------------------------------------------------
# Optional: upload source maps to Sentry
# --------------------------------------------------------------------------
# Runs when SENTRY_AUTH_TOKEN, SENTRY_ORG, and SENTRY_PROJECT are all set.
# SENTRY_RELEASE defaults to unversioned if not provided.
# Maps remain in the image; whether they are served is controlled by
# the SERVE_SOURCE_MAPS env var (Caddy returns 404 unless it is "true").

upload_sourcemaps() {
    if [ -z "${SENTRY_AUTH_TOKEN:-}" ] || \
       [ -z "${SENTRY_ORG:-}" ] || \
       [ -z "${SENTRY_PROJECT:-}" ]; then
        return
    fi
    echo "Uploading source maps to Sentry..."
    local args="--org $SENTRY_ORG --project $SENTRY_PROJECT"
    if [ -n "${SENTRY_RELEASE:-}" ]; then
        args="$args --release $SENTRY_RELEASE"
    fi
    if [ -n "${SENTRY_URL:-}" ]; then
        args="$args --url $SENTRY_URL"
    fi
    # shellcheck disable=SC2086  # $args holds multiple flags; intentional word-splitting
    sentry-cli sourcemaps upload $args /srv/ui/assets/
    echo "Source maps uploaded."
}

# Only `all` mode serves the UI via the bundled Caddy, so only upload there.
# Single-service replicas (api, gateway, mcp, ...) would otherwise redundantly
# re-upload the same maps on every start/restart.
if [ "$IMBI_SERVICE" = "all" ]; then
    upload_sourcemaps
fi

# --------------------------------------------------------------------------
# Service startup
# --------------------------------------------------------------------------

start_api() {
    echo "Starting imbi-api on :8000..."
    IMBI_HOST=0.0.0.0 IMBI_PORT=8000 imbi-api serve &

    echo "Waiting for imbi-api to become healthy..."
    local attempts=0
    local max_attempts=30
    until python3 -c "
import os
from urllib import parse
import http.client
parsed = parse.urlparse(os.environ.get('IMBI_API_URL', ''))
try:
    conn = http.client.HTTPConnection('localhost', 8000, timeout=2)
    conn.request('GET', f'{parsed.path.removesuffix(\"/\")}/status')
    resp = conn.getresponse()
    exit(0 if resp.status == 200 else 1)
except Exception:
    exit(1)
" 2>/dev/null; do
        attempts=$((attempts + 1))
        if [ "$attempts" -ge "$max_attempts" ]; then
            echo "ERROR: imbi-api did not become healthy after ${max_attempts}s" >&2
            exit 1
        fi
        sleep 1
    done
    echo "imbi-api is healthy"
}

start_assistant() {
    echo "Starting imbi-assistant on :8002..."
    imbi-assistant serve --host 0.0.0.0 --port 8002 &
}

start_gateway() {
    echo "Starting imbi-gateway on :8003..."
    imbi-gateway serve --host 0.0.0.0 --port 8003 &
}

start_mcp() {
    echo "Starting imbi-mcp on :8001..."
    imbi-mcp serve --transport streamable-http --host 0.0.0.0 --port 8001 &
}

start_slackbot() {
    echo "Starting imbi-slackbot on :8004..."
    imbi-slackbot serve --host 0.0.0.0 --port 8004 &
}

start_scheduler() {
    echo "Starting imbi-scheduler on :8005..."
    imbi-scheduler serve --host 0.0.0.0 --port 8005 &
}

start_caddy() {
    echo "Starting caddy reverse proxy on :8080..."
    caddy run --config /etc/caddy/Caddyfile &
}

case "$IMBI_SERVICE" in
    all)
        start_api
        start_assistant
        start_gateway
        start_mcp
        # Slack bot is optional in 'all' mode: start it only when its tokens
        # are present (mirroring the validation above). Unconfigured, it would
        # exit immediately and trip the `wait -n` below, tearing down the whole
        # container.
        if [ -n "${SLACK_APP_TOKEN:-}" ] && \
           [ -n "${SLACK_BOT_TOKEN:-}" ] && \
           [ -n "${ANTHROPIC_API_KEY:-}" ]; then
            start_slackbot
        else
            echo "imbi-slackbot disabled (needs SLACK_APP_TOKEN, SLACK_BOT_TOKEN, ANTHROPIC_API_KEY)"
        fi
        # Optional on the same terms as the slack bot: without its own
        # service-account credentials every api-target firing would resolve no
        # principal and be skipped, so a scheduler that cannot run anything is
        # not started rather than left logging skips forever.
        if [ -n "${IMBI_SCHEDULER_SA_CLIENT_ID:-}" ] && \
           [ -n "${IMBI_SCHEDULER_SA_CLIENT_SECRET:-}" ]; then
            start_scheduler
        else
            echo "imbi-scheduler disabled (needs IMBI_SCHEDULER_SA_CLIENT_ID, IMBI_SCHEDULER_SA_CLIENT_SECRET)"
        fi
        start_caddy
        ;;
    api)
        IMBI_HOST=0.0.0.0 IMBI_PORT=8000 exec imbi-api serve
        ;;
    assistant)
        exec imbi-assistant serve --host 0.0.0.0 --port 8002
        ;;
    gateway)
        exec imbi-gateway serve --host 0.0.0.0 --port 8003
        ;;
    mcp)
        exec imbi-mcp serve --transport streamable-http --host 0.0.0.0 --port 8001
        ;;
    scheduler)
        exec imbi-scheduler serve --host 0.0.0.0 --port 8005
        ;;
    slackbot)
        exec imbi-slackbot serve --host 0.0.0.0 --port 8004
        ;;
    *)
        echo "ERROR: Unknown service '$IMBI_SERVICE'" >&2
        echo "Valid values: all, api, assistant, gateway, mcp, scheduler, slackbot" >&2
        exit 1
        ;;
esac

# When running all services, wait for any child to exit
wait -n
exit $?
