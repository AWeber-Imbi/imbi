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
    eval val="\${$1:-}"
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
    *)
        echo "ERROR: Unknown service '$IMBI_SERVICE'" >&2
        echo "Valid values: all, api, assistant, gateway, mcp" >&2
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
    sentry-cli sourcemaps upload $args /srv/ui/assets/
    echo "Source maps uploaded."
}

upload_sourcemaps

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
    *)
        echo "ERROR: Unknown service '$IMBI_SERVICE'" >&2
        echo "Valid values: all, api, assistant, gateway, mcp" >&2
        exit 1
        ;;
esac

# When running all services, wait for any child to exit
wait -n
exit $?
