[doc("Bootstrap the environment and run the service in the foreground")]
[group("Testing")]
serve *ARGS:
    -uv run imbi-gateway serve {{ARGS}}

# I would use [no-exit-message] here instead but it doesn't prevent a message
# when I Ctrl+C the process (https://github.com/casey/just/issues/2895)

[default]
[private]
ci: lint test

[doc("Set up your development environment")]
[group("Environment")]
setup:
    uv sync --all-groups --all-extras --frozen
    uv run pre-commit install --install-hooks --overwrite

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
