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

[doc("Run tests")]
[group("Testing")]
test *FILES: setup
    #!/usr/bin/env sh
    set -e
    env_args=""
    if [ -f .env ]; then
      env_args="--env-file .env"
    fi
    if [ -z "{{ FILES }}" ]; then
      uv run $env_args coverage run -m pytest tests
      uv run coverage report
      uv run coverage xml -o build/coverage.xml
    else
      uv run $env_args pytest {{ FILES }}
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
    rm -f .coverage .env
    rm -fR build

[confirm]
[doc("Remove caches, virtual env, and output files")]
[group("Environment")]
real-clean: clean
    rm -fR .venv .*_cache dist
