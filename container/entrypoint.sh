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
    # without it and 404s -- including the token request, whose 404 becomes an
    # IdentityError, so every such firing is recorded as skipped.
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
        # are not required here. The scheduler's service-account credentials
        # are not required either, but for the opposite reason: this mode
        # seeds them itself when the environment does not supply them (see
        # `provision_internal_credentials`).
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

random_token() {
    tr -dc 'A-Za-z0-9' < /dev/urandom | head -c "${1:-43}"
}

random_hex() {
    tr -dc 'a-f0-9' < /dev/urandom | head -c 32
}

# 'all' mode only. imbi-scheduler and imbi-gateway authenticate to imbi-api
# as their own service accounts, so both need a credential before they can
# do anything: without one every api-target firing is skipped, and every
# gateway action gets a 401. `setup-service-accounts` seeds whatever the
# environment supplies, so a deployment that already holds these secrets
# keeps them. One that does not gets a pair minted here -- in a single
# container nothing outside it ever needs to know the values, so generating
# them per boot is cheaper than asking an operator to invent them.
provision_internal_credentials() {
    minted_scheduler=0
    minted_gateway=0
    # Both halves or neither. Minting on an empty client id alone would
    # overwrite a secret the operator did set, and `setup-service-accounts`
    # seeds what the environment holds -- so the value they meant to be in
    # use would be replaced by a generated one without anything saying so.
    if [ -z "${IMBI_SCHEDULER_SA_CLIENT_ID:-}" ] && \
       [ -z "${IMBI_SCHEDULER_SA_CLIENT_SECRET:-}" ]; then
        # A fixed client_id so a restart re-points the same credential
        # instead of accumulating one node per boot.
        export IMBI_SCHEDULER_SA_CLIENT_ID="cc_imbi_scheduler_all_mode"
        IMBI_SCHEDULER_SA_CLIENT_SECRET="$(random_token)"
        export IMBI_SCHEDULER_SA_CLIENT_SECRET
        minted_scheduler=1
    elif [ -z "${IMBI_SCHEDULER_SA_CLIENT_ID:-}" ] || \
         [ -z "${IMBI_SCHEDULER_SA_CLIENT_SECRET:-}" ]; then
        echo "ERROR: set IMBI_SCHEDULER_SA_CLIENT_ID and IMBI_SCHEDULER_SA_CLIENT_SECRET together, or neither" >&2
        return 1
    fi
    if [ -z "${ACTIONS_IMBI_TOKEN:-}" ]; then
        ACTIONS_IMBI_TOKEN="ik_$(random_hex)_$(random_token)"
        export ACTIONS_IMBI_TOKEN
        minted_gateway=1
    fi
    if imbi-api setup-service-accounts; then
        return 0
    fi
    # Seeding failed, so anything minted above authenticates nobody. Drop
    # it rather than hand a service a credential the database has never
    # heard of: "not configured" names the real problem, a 401 does not.
    if [ "$minted_scheduler" = 1 ]; then
        unset IMBI_SCHEDULER_SA_CLIENT_ID IMBI_SCHEDULER_SA_CLIENT_SECRET
    fi
    if [ "$minted_gateway" = 1 ]; then
        unset ACTIONS_IMBI_TOKEN
    fi
    return 1
}

case "$IMBI_SERVICE" in
    all)
        # imbi-gateway's default upstream is the service name imbi-api, which
        # in a single container resolves to nothing; imbi-api is right here.
        export ACTIONS_IMBI_URL="${ACTIONS_IMBI_URL:-http://localhost:8000}"
        # Before any service starts: imbi-gateway reads ACTIONS_IMBI_TOKEN
        # when it handles its first action, and imbi-scheduler its client
        # credential at every firing.
        if provision_internal_credentials; then
            scheduler_configured=1
        else
            scheduler_configured=0
            echo "WARNING: could not seed internal service accounts; run 'imbi-api setup' first" >&2
        fi
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
        # `provision_internal_credentials` above seeds or adopts the
        # scheduler's service-account credential, so the only case left is
        # one where seeding itself failed. Starting then would leave the
        # scheduler skipping every api-target firing for want of a
        # principal, so it stays out.
        if [ "$scheduler_configured" = 1 ]; then
            start_scheduler
        else
            echo "imbi-scheduler disabled (no service-account credential could be seeded)"
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
