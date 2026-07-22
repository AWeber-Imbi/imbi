image := "ghcr.io/aweber-imbi/imbi"
okteto_services := "imbi-api imbi-assistant imbi-gateway imbi-mcp imbi-slackbot imbi-ui"

export UV_FROZEN := "1"

set dotenv-load

[default]
[doc("Display the available commands")]
[group("Development")]
@help:
    just --list

[private]
ci: lint test

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

[doc("Set up your development environment")]
[group("Environment")]
setup:
    uv sync --all-groups --all-extras --frozen
    uv run pre-commit install --install-hooks --overwrite

[private]
docker:
    #!/usr/bin/env sh
    set -e
    get_port() {
        if port="$(docker compose -f compose.ci.yaml port "$@")"; then
            echo "${port##*:}"
            return 0
        fi
        echo "docker compose port $@ failed" >&2
        return 1
    }
    docker compose -f compose.ci.yaml up -d --wait --wait-timeout 120 || (docker compose -f compose.ci.yaml logs && false)
    docker compose -f compose.ci.yaml exec -T clickhouse clickhouse client -q "CREATE DATABASE IF NOT EXISTS imbi"
    test_host="${TEST_HOST:-127.0.0.1}"
    if test -f .env.test; then
        if grep -q '^IMBI_AUTH_JWT_SECRET=' .env.test; then
            jwt_secret=$(grep -m1 '^IMBI_AUTH_JWT_SECRET=' .env.test | cut -d= -f2- | tr -d '\r"')
        fi
        if grep -q '^IMBI_AUTH_ENCRYPTION_KEY=' .env.test; then
            encryption_key=$(grep -m1 '^IMBI_AUTH_ENCRYPTION_KEY=' .env.test | cut -d= -f2- | tr -d '\r"')
        fi
    fi
    if test -z "${jwt_secret:-}"; then
        jwt_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    fi
    if test -z "${encryption_key:-}"; then
        encryption_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32) + '=')")
    fi
    cat>".env.test"<<-EOF
    TEST_HOST="$test_host"
    CLICKHOUSE_URL="clickhouse+http://default:password@$test_host:$(get_port clickhouse 8123)/imbi"
    FILE_CACHE_ENABLED="no"
    IMBI_AUTH_ENCRYPTION_KEY="$encryption_key"
    IMBI_AUTH_JWT_SECRET="$jwt_secret"
    IMBI_API_URL=http://localhost:8000
    IMBI_EMAIL_ENABLED="true"
    IMBI_EMAIL_SMTP_HOST="$test_host"
    IMBI_EMAIL_SMTP_PORT="$(get_port mailpit 1025)"
    IMBI_EMAIL_SMTP_USE_TLS="false"
    IMBI_EMAIL_FROM_EMAIL="noreply@imbi.example"
    IMBI_EMAIL_FROM_NAME="Imbi Development"
    MAILPIT_SMTP_PORT="$(get_port mailpit 1025)"
    MAILPIT_API_URL="http://$test_host:$(get_port mailpit 8025)"
    MAILPIT_WEB_PORT="$(get_port mailpit 8025)"
    OTEL_LOGS_EXPORTER="none"
    OTEL_METRICS_EXPORTER="none"
    OTEL_TRACES_EXPORTER="otlp"
    OTEL_EXPORTER_OTLP_ENDPOINT="$test_host:$(get_port jaeger 4317)"
    OTEL_EXPORTER_OTLP_TRACES_INSECURE="true"
    OTEL_RESOURCE_ATTRIBUTES="service.name=imbi-api,service.environment=development"
    OTEL_SERVICE_NAME="imbi-api"
    POSTGRES_URL="postgresql://postgres:secret@$test_host:$(get_port postgres 5432)/imbi"
    S3_ENDPOINT_URL="http://$test_host:$(get_port localstack 4566)"
    S3_ACCESS_KEY="test"
    S3_SECRET_KEY="test"
    S3_BUCKET="imbi-uploads"
    S3_REGION="us-east-1"
    VALKEY_URL="valkey://$test_host:$(get_port valkey 6379)"
    EOF

[doc("Remove runtime development artifacts")]
[group("Environment")]
clean:
    docker compose -f compose.ci.yaml down --remove-orphans --volumes
    rm -f .coverage .env.test
    rm -fR build docs/site

[confirm]
[doc("Remove caches, virtual env, and output files")]
[group("Environment")]
real-clean: clean
    rm -fR .venv .*_cache dist apps/ui/node_modules

# ---------------------------------------------------------------------------
# Testing
# ---------------------------------------------------------------------------

[doc("Run tests (all suites with coverage, or specific files)")]
[group("Testing")]
test *FILES: setup docker
    #!/usr/bin/env sh
    set -e
    if [ -z "{{ FILES }}" ]; then
      uv run --env-file .env.test coverage run -m pytest tests
      uv run coverage report
      uv run coverage xml -o build/coverage.xml
    else
      uv run --env-file .env.test pytest {{ FILES }}
    fi

[doc("Run one suite with its own coverage floor, e.g. `just test-suite common 90`")]
[group("Testing")]
test-suite suite floor="85": setup docker
    #!/usr/bin/env sh
    set -e
    module="imbi.$(echo '{{ suite }}' | tr / .)"
    uv run --env-file .env.test pytest 'tests/{{ suite }}' \
        --cov="$module" --cov-fail-under='{{ floor }}'

[doc("Run linters")]
[group("Testing")]
lint: setup
    uv run pre-commit run --all-files
    uv run basedpyright

[doc("Reformat code (optionally pass specific files)")]
[group("Development")]
format *FILES: setup
    #!/usr/bin/env sh
    if [ "{{ FILES }}" = '' ]; then
        args='--all-files'
    else
        args='--files {{ FILES }}'
    fi
    uv run pre-commit run ruff-format $args
    uv run pre-commit run tombi-format $args

# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

[doc("Install UI dependencies")]
[group("UI")]
[working-directory("apps/ui")]
ui-install:
    npm ci

[doc("Lint the UI")]
[group("UI")]
[working-directory("apps/ui")]
ui-lint: ui-install
    npm run lint
    npm run format:check

[doc("Run the UI tests")]
[group("UI")]
[working-directory("apps/ui")]
ui-test: ui-install
    npm run test

[doc("Build the UI")]
[group("UI")]
[working-directory("apps/ui")]
ui-build: ui-install
    npm run build

[private]
ui-ci: ui-lint ui-test ui-build

# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------

[doc("Build the documentation")]
[group("Docs")]
docs: setup
    uv run --group docs mkdocs build --strict -f docs/mkdocs.yml

[doc("Serve documentation locally for development")]
[group("Docs")]
docs-serve: setup
    uv run --group docs mkdocs serve -f docs/mkdocs.yml -a localhost:8088

# ---------------------------------------------------------------------------
# Docker image
# ---------------------------------------------------------------------------

[doc("Build the Docker image")]
[group("Build Docker")]
build tag="latest":
    docker build --build-arg VITE_GIT_REF={{ tag }} -t {{ image }}:{{ tag }} .

[doc("Build the Docker image and tag as both version and latest")]
[group("Build Docker")]
release tag:
    docker build --build-arg VITE_GIT_REF={{ tag }} -t {{ image }}:{{ tag }} -t {{ image }}:latest .

[doc("Build and initialize the production image locally")]
[group("Development")]
bootstrap:
    docker compose up --build --wait --detach
    docker compose exec imbi imbi-api setup

[doc("Destroy the local production-image environment")]
[group("Development")]
teardown:
    docker compose down --remove-orphans --volumes

# ---------------------------------------------------------------------------
# Okteto dev environment
# ---------------------------------------------------------------------------

[doc("Deploy the Okteto environment, forward services, and start dev sessions")]
[group("Okteto")]
start: deploy forward-dev up

[doc("Tear down dev sessions, forwards, and the Okteto environment")]
[group("Okteto")]
stop: stop-forward-dev down destroy

[doc("Deploy the Okteto dev environment")]
[group("Okteto")]
deploy:
    okteto deploy

[doc("Destroy the Okteto dev environment")]
[group("Okteto")]
destroy:
    okteto destroy

[doc("Seed roles/permissions and create the initial admin user")]
[group("Okteto")]
seed:
    okteto exec imbi-api -- uv run imbi-api setup

# Start `okteto up` in detached tmux sessions. With no argument, starts
# every service; with a service name, starts just that one, e.g.
# `just up imbi-slackbot`.
[group("Okteto")]
up service="" flag="":
    #!/usr/bin/env bash
    set -uo pipefail
    if [ -n "{{ service }}" ]; then
        services="{{ service }}"
        echo "Starting okteto up session for {{ service }}..."
    else
        services="{{ okteto_services }}"
        echo "Starting all okteto up sessions..."
    fi
    for service in $services; do
        echo "→ $service"
        tmux new-session -d -s "$service" "okteto up {{ flag }} $service" > /dev/null 2>&1 || true
    done

[group("Okteto")]
down:
    #!/usr/bin/env bash
    echo "Stopping all okteto up sessions..."
    for service in {{ okteto_services }}; do
        echo "→ $service"
        tmux kill-session -t "$service" > /dev/null 2>&1 || true
    done

[group("Okteto")]
status:
    tmux ls | grep ^imbi- || echo 'no okteto up sessions running'

# Attach to a service's okteto up tmux session, e.g. `just attach imbi-api`
[group("Okteto")]
attach service:
    tmux attach -t {{ service }}

# ---------------------------------------------------------------------------
# Cluster forwards and data sync
# ---------------------------------------------------------------------------

# Forward every service in the dev namespace via kubefwd. Services
# become reachable by their in-cluster name (postgres:5432,
# clickhouse:8123/9000) through /etc/hosts entries kubefwd manages.
# kubefwd runs as root: sudo is primed in the foreground, then kubefwd
# is backgrounded in this same shell so it keeps the cached credential
# (a detached tmux pane gets a fresh pty and would re-prompt).
[group("Forwards")]
forward-dev:
    #!/usr/bin/env bash
    set -uo pipefail
    kubectl config use-context testing
    if ! kubectl get pods --namespace gavinr > /dev/null 2>&1; then
        echo "Error: cannot reach the cluster. Run 'aws sso login' and try again." >&2
        exit 1
    fi
    if pgrep -f 'kubefwd svc --namespace gavinr' > /dev/null; then
        echo "kubefwd already forwarding namespace gavinr"
        exit 0
    fi
    echo "Forwarding all services in namespace gavinr via kubefwd (postgres:5432, clickhouse:8123/9000)"
    sudo -v
    nohup sudo kubefwd svc --namespace gavinr --context testing \
        < /dev/null > '{{ justfile_directory() }}/.kubefwd-dev.log' 2>&1 &
    disown

[group("Forwards")]
stop-forward-dev:
    @-sudo pkill -f 'kubefwd svc --namespace gavinr'

# Forward every service in the production namespace via kubefwd. See
# forward-dev for how sudo/backgrounding work. Production services
# resolve as imbi-postgres-ro:5432 and clickhouse-imbi:8123/9000.
[group("Forwards")]
forward-production:
    #!/usr/bin/env bash
    set -uo pipefail
    kubectl config use-context infrastructure
    if ! kubectl get pods --namespace imbi > /dev/null 2>&1; then
        echo "Error: cannot reach the cluster. Run 'aws sso login' and try again." >&2
        exit 1
    fi
    if pgrep -f 'kubefwd svc --namespace imbi' > /dev/null; then
        echo "kubefwd already forwarding namespace imbi"
        exit 0
    fi
    echo "Forwarding all services in namespace imbi via kubefwd (imbi-postgres-ro:5432, clickhouse-imbi:8123/9000)"
    sudo -v
    nohup sudo kubefwd svc --namespace imbi --context infrastructure \
        < /dev/null > '{{ justfile_directory() }}/.kubefwd-production.log' 2>&1 &
    disown

[group("Forwards")]
stop-forward-production:
    @-sudo pkill -f 'kubefwd svc --namespace imbi'

# Refresh the dev environment with production data. Stage 1 is read-only
# against production (pg_dump + clickhouse export); stage 2 destructively
# restores both into dev after validating the targets.
[group("Data")]
sync-prod-to-dev: backup-production restore-dev

# Stage 1 of sync-prod-to-dev: export production postgres (plain SQL
# dump) and clickhouse (Native-format file per table) to ./backups/.
# Read-only. Native format is used instead of Parquet because Parquet
# cannot encode Object/JSON columns (e.g. events.metadata).
[group("Data")]
backup-production:
    #!/usr/bin/env bash
    set -euo pipefail
    set -a
    source '{{ justfile_directory() }}/.env.production'
    set +a
    backup_dir='{{ justfile_directory() }}/backups'
    mkdir -p "$backup_dir/clickhouse"
    rm -f "$backup_dir/clickhouse"/*.native
    just stop-forward-dev
    just forward-production
    trap 'just stop-forward-production' EXIT
    ch_hostpart="${CLICKHOUSE_URL#*://}"
    ch_creds="${ch_hostpart%@*}"
    ch_user="${ch_creds%%:*}"
    ch_pass="${ch_creds#*:}"
    ch_authority="${ch_hostpart#*@}"
    ch_db="${ch_authority##*/}"
    ch_endpoint="http://${ch_authority%%/*}/"
    pg_authority="${POSTGRES_URL#*://}"
    pg_authority="${pg_authority#*@}"
    pg_hostport="${pg_authority%%/*}"
    pg_host="${pg_hostport%%:*}"
    pg_port="${pg_hostport##*:}"
    echo '→ waiting for kubefwd to become ready'
    for i in $(seq 1 30); do
        if pg_isready -h "$pg_host" -p "$pg_port" -q 2>/dev/null; then break; fi
        if [ "$i" = 30 ]; then echo 'Error: postgres forward never became ready' >&2; exit 1; fi
        sleep 1
    done
    for i in $(seq 1 30); do
        if curl -fs "${ch_endpoint}ping" > /dev/null 2>&1; then break; fi
        if [ "$i" = 30 ]; then echo 'Error: clickhouse forward never became ready' >&2; exit 1; fi
        sleep 1
    done
    echo '→ dumping production postgres to backups/imbi.sql'
    pg_dump --dbname "$POSTGRES_URL" --format plain --no-owner --no-privileges \
        --file "$backup_dir/imbi.sql"
    tables=$(curl -fsS -u "$ch_user:$ch_pass" "$ch_endpoint" --data-binary \
        "SELECT name FROM system.tables WHERE database = '$ch_db' AND engine NOT IN ('View', 'MaterializedView') AND name NOT LIKE '.inner%' FORMAT TSV")
    for table in $tables; do
        echo "→ exporting clickhouse table $table"
        curl -fsS -u "$ch_user:$ch_pass" "$ch_endpoint" \
            --data-binary "SELECT * FROM \"$ch_db\".\"$table\" FORMAT Native" \
            -o "$backup_dir/clickhouse/$table.native"
    done
    echo '→ production export complete'

# Stage 2 of sync-prod-to-dev: DESTRUCTIVE. Runs both restore steps
# back-to-back. ClickHouse tables that only exist once the dev services
# have booted (startup migrations create the DDL) are skipped — run
# restore-dev-postgres, start the services, then restore-dev-clickhouse
# to sequence around that.
[group("Data")]
restore-dev: restore-dev-postgres restore-dev-clickhouse

# DESTRUCTIVE. Drops and recreates the dev imbi postgres database, then
# restores ./backups/imbi.sql and repairs the AGE catalog. Validates
# the target is dev before writing: kubectl context must be 'testing'
# and postgres must not be a read-only replica (production forwards
# imbi-postgres-ro). Dev credentials also fail auth against production
# outright.
[group("Data")]
restore-dev-postgres:
    #!/usr/bin/env bash
    set -euo pipefail
    set -a
    source '{{ justfile_directory() }}/.env.dev'
    set +a
    backup_dir='{{ justfile_directory() }}/backups'
    if [ ! -f "$backup_dir/imbi.sql" ]; then
        echo "Error: $backup_dir/imbi.sql not found; run 'just backup-production' first" >&2
        exit 1
    fi
    if pgrep -f 'kubefwd svc --namespace imbi' > /dev/null; then
        echo "Error: production kubefwd is running; run 'just stop-forward-production' first" >&2
        exit 1
    fi
    just forward-dev
    if [ "$(kubectl config current-context)" != 'testing' ]; then
        echo "Error: kubectl context is '$(kubectl config current-context)', expected 'testing'" >&2
        exit 1
    fi
    pg_authority="${POSTGRES_URL#*://}"
    pg_authority="${pg_authority#*@}"
    pg_hostport="${pg_authority%%/*}"
    pg_host="${pg_hostport%%:*}"
    pg_port="${pg_hostport##*:}"
    echo '→ waiting for the postgres forward to become ready'
    for i in $(seq 1 30); do
        if pg_isready -h "$pg_host" -p "$pg_port" -q 2>/dev/null; then break; fi
        if [ "$i" = 30 ]; then echo 'Error: postgres forward never became ready' >&2; exit 1; fi
        sleep 1
    done
    admin_url="${POSTGRES_URL%/*}/postgres"
    if [ "$(psql "$admin_url" -tAc 'SELECT pg_is_in_recovery()')" != 'f' ]; then
        echo "Error: postgres at $pg_host:$pg_port is a read-only replica — this is not dev, refusing to restore" >&2
        exit 1
    fi
    echo '→ dropping and recreating the dev imbi database'
    psql "$admin_url" -v ON_ERROR_STOP=1 -c 'DROP DATABASE IF EXISTS imbi WITH (FORCE)'
    psql "$admin_url" -v ON_ERROR_STOP=1 -c 'CREATE DATABASE imbi'
    psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS age'
    echo '→ restoring backups/imbi.sql (AGE catalog errors are expected; see backups/restore.log)'
    psql "$POSTGRES_URL" \
        -c "LOAD 'age'" \
        -c 'SET search_path = ag_catalog, "$user", public' \
        -f "$backup_dir/imbi.sql" > "$backup_dir/restore.log" 2>&1
    errors=$(grep -c 'ERROR:' "$backup_dir/restore.log" || true)
    echo "  restore finished with $errors errors logged"
    graphid=$(psql "$POSTGRES_URL" -tAc "SELECT graphid FROM ag_catalog.ag_graph WHERE name = 'imbi'")
    if [ -z "$graphid" ]; then
        echo "Error: AGE graph 'imbi' missing after restore" >&2
        exit 1
    fi
    # AGE requires graphid == the imbi schema's pg_namespace OID, but the
    # dump carries production's OID; queries then fail with "graph with
    # oid N does not exist". The ag_label FK isn't deferrable and
    # name/namespace are unique, hence the rename-insert-repoint-delete.
    ns_oid=$(psql "$POSTGRES_URL" -tAc "SELECT oid FROM pg_namespace WHERE nspname = 'imbi'")
    if [ "$graphid" != "$ns_oid" ]; then
        echo "→ rewriting AGE graph oid $graphid -> $ns_oid"
        psql "$POSTGRES_URL" --single-transaction -v ON_ERROR_STOP=1 <<SQL
    UPDATE ag_catalog.ag_graph SET name = '_imbi_stale', namespace = 'public' WHERE graphid = ${graphid};
    INSERT INTO ag_catalog.ag_graph (graphid, name, namespace) VALUES (${ns_oid}, 'imbi', 'imbi');
    UPDATE ag_catalog.ag_label SET graph = ${ns_oid} WHERE graph = ${graphid};
    DELETE FROM ag_catalog.ag_graph WHERE graphid = ${graphid};
    SQL
        graphid=$ns_oid
    fi
    echo '→ registering AGE labels missing from ag_catalog.ag_label'
    psql "$POSTGRES_URL" -v ON_ERROR_STOP=1 <<SQL
    INSERT INTO ag_catalog.ag_label (name, graph, id, kind, relation, seq_name)
    SELECT
        tablename,
        ${graphid},
        (SELECT max(id) FROM ag_catalog.ag_label WHERE graph = ${graphid})
            + row_number() OVER (ORDER BY tablename),
        CASE WHEN tablename ~ '^[A-Z][a-z]' THEN 'v' ELSE 'e' END,
        ('imbi."' || tablename || '"')::regclass,
        tablename || '_id_seq'
    FROM pg_tables
    WHERE schemaname = 'imbi'
      AND tablename NOT IN
        (SELECT name FROM ag_catalog.ag_label WHERE graph = ${graphid});
    SQL
    remaining=$(psql "$POSTGRES_URL" -tAc "SELECT count(*) FROM pg_tables WHERE schemaname = 'imbi' AND tablename NOT IN (SELECT name FROM ag_catalog.ag_label WHERE graph = ${graphid})")
    if [ "$remaining" != '0' ]; then
        echo "Error: $remaining imbi label tables remain unregistered in ag_catalog.ag_label" >&2
        exit 1
    fi
    echo '→ dev postgres restore complete; dev port-forwards left running'

# DESTRUCTIVE. Truncates every dev clickhouse table and reloads them
# from ./backups/clickhouse/*.native. Tables missing in dev are skipped
# with a warning — start the dev services first so startup migrations
# create the DDL. Validates the target is dev before writing: kubectl
# context must be 'testing' and clickhouse must not report a production
# (chi-*) hostname. Dev credentials also fail auth against production
# outright.
[group("Data")]
restore-dev-clickhouse:
    #!/usr/bin/env bash
    set -euo pipefail
    set -a
    source '{{ justfile_directory() }}/.env.dev'
    set +a
    backup_dir='{{ justfile_directory() }}/backups'
    if ! compgen -G "$backup_dir/clickhouse/*.native" > /dev/null; then
        echo "Error: no .native files in $backup_dir/clickhouse; run 'just backup-production' first" >&2
        exit 1
    fi
    if pgrep -f 'kubefwd svc --namespace imbi' > /dev/null; then
        echo "Error: production kubefwd is running; run 'just stop-forward-production' first" >&2
        exit 1
    fi
    just forward-dev
    if [ "$(kubectl config current-context)" != 'testing' ]; then
        echo "Error: kubectl context is '$(kubectl config current-context)', expected 'testing'" >&2
        exit 1
    fi
    ch_hostpart="${CLICKHOUSE_URL#*://}"
    ch_creds="${ch_hostpart%@*}"
    ch_user="${ch_creds%%:*}"
    ch_pass="${ch_creds#*:}"
    ch_authority="${ch_hostpart#*@}"
    ch_db="${ch_authority##*/}"
    ch_endpoint="http://${ch_authority%%/*}/"
    echo '→ waiting for the clickhouse forward to become ready'
    for i in $(seq 1 30); do
        if curl -fs "${ch_endpoint}ping" > /dev/null 2>&1; then break; fi
        if [ "$i" = 30 ]; then echo 'Error: clickhouse forward never became ready' >&2; exit 1; fi
        sleep 1
    done
    ch_hostname=$(curl -fsS -u "$ch_user:$ch_pass" "$ch_endpoint" \
        --data-binary 'SELECT hostName()')
    case "$ch_hostname" in
        chi-*)
            echo "Error: clickhouse reports hostname '$ch_hostname', which looks like production — refusing to truncate" >&2
            exit 1
            ;;
    esac
    # Includes materialized-view .inner% tables: they are truncated (the
    # MVs rebuild them as source tables load) but never loaded directly.
    echo '→ truncating dev clickhouse tables'
    dev_tables=$(curl -fsS -u "$ch_user:$ch_pass" "$ch_endpoint" --data-binary \
        "SELECT name FROM system.tables WHERE database = '$ch_db' AND engine NOT IN ('View', 'MaterializedView') FORMAT TSV")
    for table in $dev_tables; do
        echo "  truncating $table"
        curl -fsS -u "$ch_user:$ch_pass" "$ch_endpoint" \
            --data-binary "TRUNCATE TABLE \"$ch_db\".\"$table\""
    done
    for file in "$backup_dir/clickhouse/"*.native; do
        if [ ! -e "$file" ]; then continue; fi
        table=$(basename "$file" .native)
        exists=$(curl -fsS -u "$ch_user:$ch_pass" "$ch_endpoint" --data-binary \
            "SELECT count() FROM system.tables WHERE database = '$ch_db' AND name = '$table'")
        if [ "$exists" != '1' ]; then
            echo "  Warning: table $table does not exist in dev clickhouse, skipping" >&2
            continue
        fi
        echo "→ loading clickhouse table $table"
        # Force compact parts: JSON columns in wide parts write a file
        # per dynamic path per part, exhausting the volume's inodes.
        curl -fsS -u "$ch_user:$ch_pass" "$ch_endpoint" --data-binary \
            "ALTER TABLE \"$ch_db\".\"$table\" MODIFY SETTING min_bytes_for_wide_part = 10737418240, min_rows_for_wide_part = 100000000"
        # Small insert blocks: the dev clickhouse pod has a ~7GB memory
        # cap and OOMs squashing default-sized blocks of JSON columns.
        # No curl -f: on failure we want clickhouse's error body.
        http_code=$(curl -sS -u "$ch_user:$ch_pass" -X POST -T "$file" \
            -o "$backup_dir/load-response.txt" -w '%{http_code}' \
            "${ch_endpoint}?query=INSERT%20INTO%20%22$ch_db%22.%22$table%22%20FORMAT%20Native&min_insert_block_size_rows=65536&min_insert_block_size_bytes=33554432")
        if [ "$http_code" != '200' ]; then
            echo "  Error: INSERT into $table returned $http_code:" >&2
            cat "$backup_dir/load-response.txt" >&2
            exit 1
        fi
    done
    echo '→ dev clickhouse restore complete; dev port-forwards left running'

# Load all blueprints from ./blueprints/ into the Imbi API via upsert
# Requires IMBI_API_URL and IMBI_API_TOKEN environment variables
[group("Data")]
load-blueprints:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${IMBI_API_URL:?Set IMBI_API_URL (e.g. https://imbi-api-pse-infrastructure-testing.cloud.okteto.net)}"
    : "${IMBI_API_TOKEN:?Set IMBI_API_TOKEN to an API key (ik_...)}"
    blueprints_dir='{{ justfile_directory() }}/blueprints'
    for file in "${blueprints_dir}"/*.yaml; do
        slug=$(yq -r '.slug' "$file")
        type=$(yq -r '.type // .kind' "$file")
        payload=$(yq -o=json '.' "$file")
        echo "-> ${type}/${slug} ($(basename "$file"))"
        http_code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
            -H "Authorization: Bearer ${IMBI_API_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "${IMBI_API_URL}/blueprints/")
        if [ "$http_code" = '201' ]; then
            echo "  ${http_code} (created)"
        elif [ "$http_code" = '409' ]; then
            patch_body=$(printf '%s' "$payload" | jq '[to_entries[] | select(.key != "created_at" and .key != "updated_at" and .key != "id" and .key != "relationships") | {"op": "add", "path": ("/" + .key), "value": .value}]')
            patch_code=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH \
                -H "Authorization: Bearer ${IMBI_API_TOKEN}" \
                -H "Content-Type: application/json" \
                -d "$patch_body" \
                "${IMBI_API_URL}/blueprints/${type}/${slug}")
            if [ "$patch_code" != '200' ]; then
                echo "  Error: PATCH ${IMBI_API_URL}/blueprints/${type}/${slug} returned ${patch_code}" >&2
                exit 1
            fi
            echo "  ${patch_code} (updated)"
        else
            echo "  Error: POST ${IMBI_API_URL}/blueprints/ returned ${http_code}" >&2
            exit 1
        fi
    done

# Load all scoring policies from ./scoring-policies/ into the Imbi API
# via upsert. Requires IMBI_API_URL and IMBI_API_TOKEN environment
# variables.
[group("Data")]
load-scoring-policies:
    #!/usr/bin/env bash
    set -euo pipefail
    : "${IMBI_API_URL:?Set IMBI_API_URL (e.g. https://imbi-api-pse-infrastructure-testing.cloud.okteto.net)}"
    : "${IMBI_API_TOKEN:?Set IMBI_API_TOKEN to an API key (ik_...)}"
    policies_dir='{{ justfile_directory() }}/scoring-policies'
    for file in "${policies_dir}"/*.json; do
        slug=$(jq -r '.slug' "$file")
        payload=$(cat "$file")
        echo "-> ${slug} ($(basename "$file"))"
        http_code=$(curl -s -o /dev/null -w '%{http_code}' -X POST \
            -H "Authorization: Bearer ${IMBI_API_TOKEN}" \
            -H "Content-Type: application/json" \
            -d "$payload" \
            "${IMBI_API_URL}/scoring/policies/")
        if [ "$http_code" = '201' ]; then
            echo "  ${http_code} (created)"
        elif [ "$http_code" = '409' ]; then
            patch_body=$(printf '%s' "$payload" | jq '[to_entries[] | select(.key != "created_at" and .key != "updated_at" and .key != "id" and .key != "slug" and .key != "category") | {"op": "add", "path": ("/" + .key), "value": .value}]')
            patch_code=$(curl -s -o /dev/null -w '%{http_code}' -X PATCH \
                -H "Authorization: Bearer ${IMBI_API_TOKEN}" \
                -H "Content-Type: application/json" \
                -d "$patch_body" \
                "${IMBI_API_URL}/scoring/policies/${slug}")
            if [ "$patch_code" != '200' ]; then
                echo "  Error: PATCH ${IMBI_API_URL}/scoring/policies/${slug} returned ${patch_code}" >&2
                exit 1
            fi
            echo "  ${patch_code} (updated)"
        else
            echo "  Error: POST ${IMBI_API_URL}/scoring/policies/ returned ${http_code}" >&2
            exit 1
        fi
    done
