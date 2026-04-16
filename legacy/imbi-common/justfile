[default]
[private]
@help:
    just --list

[private]
ci: lint test

[doc("Set up your development environment")]
[group("Environment")]
setup:
    uv sync --all-groups --all-extras --frozen
    uv run pre-commit install --install-hooks --overwrite

[private]
docker:
    #!/usr/bin/env sh
    set -eu
    port() {
        if port="$(docker compose port "$@")"; then
            echo "${port#*:}"
            return 0
        fi
        echo "docker compose port $* failed" >&2
        return 1
    }
    docker compose down --remove-orphans
    docker compose up -d --wait --wait-timeout 120 || (docker compose logs && false)
    docker compose exec clickhouse clickhouse client -q "CREATE DATABASE IF NOT EXISTS imbi"

    test_host="${TEST_HOST:-127.0.0.1}"
    cat>.env<<EOF
    TEST_HOST="$test_host"
    FILE_CACHE_ENABLED="no"
    CLICKHOUSE_URL="http://default:password@$test_host:$(port clickhouse 8123)/imbi"
    POSTGRES_URL="postgresql://postgres:secret@$test_host:$(port postgres 5432)/imbi"
    VALKEY_URL="redis://$test_host:$(port valkey 6379)"
    EOF

[doc("Generate docs")]
[group("Development")]
docs: setup
    uv run mkdocs build --strict

[doc("Run tests")]
[group("Testing")]
test *FILES: setup docker
    #!/usr/bin/env sh
    set -e
    if [ -z "{{ FILES }}" ]; then
      uv run --env-file .env coverage run -m pytest tests
      uv run coverage report
      uv run coverage xml -o build/coverage.xml
    else
      uv run --env-file .env pytest {{ FILES }}
    fi

[doc("Run linters")]
[group("Testing")]
lint: setup
    uv run pre-commit run --all-files

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

[doc("Remove runtime development artifacts")]
[group("Environment")]
clean:
    docker compose down --remove-orphans --volumes
    rm -f .coverage .env
    rm -fR build

[confirm]
[doc("Remove caches, virtual env, and output files")]
[group("Environment")]
real-clean: clean
    rm -fR .venv .*_cache dist
