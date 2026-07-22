image := "ghcr.io/aweber-imbi/imbi"

export UV_FROZEN := "1"

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
      uv run --env-file .env.test coverage run -m pytest
      uv run coverage report
      uv run coverage xml -o build/coverage.xml
    else
      uv run --env-file .env.test pytest {{ FILES }}
    fi

[doc("Run one member's suite with its own coverage floor, e.g. `just test-suite libraries/common 90`")]
[group("Testing")]
test-suite member floor="85": setup docker
    #!/usr/bin/env sh
    set -e
    m='{{ member }}'
    case "$m" in
        plugins/*) module="imbi.$(echo "$m" | tr / .)" ;;
        *) module="imbi.${m#*/}" ;;
    esac
    uv run --env-file .env.test pytest "$m/tests" \
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
