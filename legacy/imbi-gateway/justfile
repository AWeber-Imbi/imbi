[doc("Bootstrap the environment and run the service in the foreground")]
[group("Testing")]
serve *ARGS: setup docker
    -uv run --env-file=.env imbi-gateway serve {{ ARGS }}

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
    docker compose up -d --wait || (docker compose logs && false)
    pg_port=$(get_port postgres 5432)
    valkey_port=$(get_port valkey 6379)
    test_host="${TEST_HOST:-127.0.0.1}"
    cat>".env"<<-EOF
    POSTGRES_URL="postgresql://postgres:secret@$test_host:$pg_port/imbi"
    VALKEY_URL="valkey://$test_host:$valkey_port"
    EOF

[doc("Run tests")]
[group("Testing")]
test *ARGS: setup docker
    #!/usr/bin/env sh
    set -eu
    uv run --env-file=.env coverage run -m pytest {{ARGS}}
    if [ '{{ARGS}}' = '' ]; then
        uv run coverage report
        uv run coverage xml
    fi

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
    uv run pre-commit run tombi-format $args

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
