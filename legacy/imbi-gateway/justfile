[doc("Bootstrap the environment and run the service in the foreground")]
[group("Testing")]
serve *ARGS:
    -uv run imbi-gateway serve {{ARGS}}

# I would use [no-exit-message] here instead but it doesn't prevent a message
# when I Ctrl+C the process (https://github.com/casey/just/issues/2895)

[default]
[private]
ci: setup lint test

[doc("Set up your development environment")]
[group("Environment")]
setup: docker
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
    test_host="${TEST_HOST:-127.0.0.1}"
    cat>".env"<<-EOF
    POSTGRES_URL="postgresql://postgres:secret@$test_host:$pg_port"
    EOF

[doc("Run tests")]
[group("Testing")]
test:
    uv run pytest

[doc("Run linters")]
[group("Testing")]
lint:
    uv run pre-commit run --all-files
    uv run basedpyright
    uv run mypy

[doc("Remove runtime artifacts")]
[group("Environment")]
clean:
    rm -f .coverage .env
    rm -fR build

[confirm]
[doc("Remove caches, virtual env, and output files")]
[group("Environment")]
real-clean: clean
    rm -fR .venv .*_cache dist
