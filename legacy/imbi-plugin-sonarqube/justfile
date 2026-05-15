export UV_FROZEN := "1"

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

[doc("Build packages")]
[group("Development")]
build:
    uv build --clear

[doc("Run tests")]
[group("Testing")]
test *ARGS: setup
    #!/usr/bin/env sh
    set -eu
    uv run coverage run -m pytest {{ARGS}}
    if [ '{{ARGS}}' = '' ]; then
        uv run coverage report
        uv run coverage xml
    fi

[doc("Run linters")]
[group("Testing")]
lint: setup
    uv run pre-commit run --all-files
    uv run pyrefly check

[doc("Reformat code (optionally pass specific files)")]
[group("Development")]
format *FILES: setup
    #!/usr/bin/env sh
    set -eu
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

[confirm]
[doc("Remove caches, virtual env, and output files")]
[group("Environment")]
real-clean: clean
    rm -fR .venv .*_cache dist
