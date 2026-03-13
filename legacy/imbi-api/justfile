export UV_FROZEN := "1"

[doc("Bootstrap the environment and run the service in the foreground")]
[group("Testing")]
serve *ARGS: setup docker
    -uv run --env-file=.env imbi-api serve {{ ARGS }}

[default]
[private]
ci: lint test

[doc("Set up your development environment")]
[group("Environment")]
setup:
    uv sync --all-groups --all-extras --frozen
    uv run pre-commit install --install-hooks --overwrite

docker:
    #!/usr/bin/env sh
    set -e
    get_port() {
        if port="$(docker compose port "$@")"; then
            echo "${port##*:}"
            return 0
        fi
        echo "docker compose port $@ failed" >&2
        return 1
    }
    docker compose up -d --wait --wait-timeout 120 || (docker compose logs && false)
    docker compose exec -T clickhouse clickhouse client -q "CREATE DATABASE IF NOT EXISTS imbi"
    test_host="${TEST_HOST:-127.0.0.1}"
    if test -f .env; then
        if grep -q '^IMBI_AUTH_JWT_SECRET=' .env; then
            jwt_secret=$(grep -m1 '^IMBI_AUTH_JWT_SECRET=' .env | cut -d= -f2- | tr -d '\r"')
        fi
        if grep -q '^IMBI_AUTH_ENCRYPTION_KEY=' .env; then
            encryption_key=$(grep -m1 '^IMBI_AUTH_ENCRYPTION_KEY=' .env | cut -d= -f2- | tr -d '\r"')
        fi
     fi
    if test -z "${jwt_secret:-}"; then
        jwt_secret=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    fi
    if test -z "${encryption_key:-}"; then
        encryption_key=$(python3 -c "import secrets; print(secrets.token_urlsafe(32) + '=')")
    fi
    cat>".env"<<-EOF
    TEST_HOST="$test_host"
    CLICKHOUSE_URL="http://default:password@$test_host:$(get_port clickhouse 8123)/imbi"
    FILE_CACHE_ENABLED="no"
    IMBI_AUTH_ENCRYPTION_KEY="$encryption_key"
    IMBI_AUTH_JWT_SECRET="$jwt_secret"
    IMBI_EMAIL_ENABLED="true"
    IMBI_EMAIL_SMTP_HOST="$test_host"
    IMBI_EMAIL_SMTP_PORT="$(get_port mailpit 1025)"
    IMBI_EMAIL_SMTP_USE_TLS="false"
    IMBI_EMAIL_FROM_EMAIL="noreply@imbi.example"
    IMBI_EMAIL_FROM_NAME="Imbi Development"
    NEO4J_URL="bolt://neo4j:neo4j@$test_host:$(get_port neo4j 7687)"
    S3_ENDPOINT_URL="http://$test_host:$(get_port localstack 4566)"
    S3_ACCESS_KEY="test"
    S3_SECRET_KEY="test"
    S3_BUCKET="imbi-uploads"
    S3_REGION="us-east-1"
    OTEL_LOGS_EXPORTER="none"
    OTEL_METRICS_EXPORTER="none"
    OTEL_TRACES_EXPORTER="otlp"
    OTEL_EXPORTER_OTLP_ENDPOINT="$test_host:$(get_port jaeger 4317)"
    OTEL_EXPORTER_OTLP_TRACES_INSECURE="true"
    OTEL_RESOURCE_ATTRIBUTES="service.name=imbi-api,service.environment=development"
    OTEL_SERVICE_NAME="imbi-api"
    MAILPIT_SMTP_PORT="$(get_port mailpit 1025)"
    MAILPIT_WEB_PORT="$(get_port mailpit 8025)"
    EOF

[doc("Run tests")]
[group("Testing")]
test: setup docker
    uv run pytest
    uv run mypy -p imbi_api

[doc("Run linters")]
[group("Testing")]
lint: setup
    uv run pre-commit run --all-files
    uv run basedpyright
    uv run mypy

[doc("Reformat code (optionally pass specific files)")]
[group("Development")]
format *FILES: setup
    #!/usr/bin/env sh
    set -x
    if [ "{{FILES}}" = '' ]; then
        args='--all-files'
    else
        args='--files {{FILES}}'
    fi
    uv run pre-commit run ruff-format $args

[doc("Remove runtime artifacts")]
[group("Environment")]
clean:
    rm -f .coverage .env
    rm -fR build
    docker compose down --remove-orphans --volumes

[confirm]
[doc("Remove caches, virtual env, and output files")]
[group("Environment")]
real-clean: clean
    rm -fR .venv .*_cache dist
