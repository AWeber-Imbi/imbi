image := "ghcr.io/aweber-imbi/imbi"

# moon (.moon/) is the task runner and owns lint/format/typecheck/test/build/
# docs plus the docker service + image tasks. These recipes are thin
# convenience wrappers; run `moon query tasks` to see everything, or call moon
# directly (e.g. `moon run api:test`, `moon ci`).

[default]
[doc("List the available moon tasks")]
[group("Development")]
@help:
    moon query tasks

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

[doc("Set up your development environment (toolchains, deps, hooks)")]
[group("Environment")]
setup:
    moon run root:setup

[doc("Boot the backing services and (re)write .env.test")]
[group("Environment")]
services:
    moon run root:services

[doc("Tear down the backing services and volumes")]
[group("Environment")]
teardown:
    moon run root:teardown

# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

[doc("Lint, type-check, and format-check every project")]
[group("Testing")]
lint:
    moon run :lint :typecheck :format

[doc("Run the full suite with aggregate coverage (single pytest session)")]
[group("Testing")]
test:
    moon run root:coverage

[doc("Run one member's suite in isolation, e.g. `just test-suite api`")]
[group("Testing")]
test-suite member:
    moon run {{ member }}:test

# ---------------------------------------------------------------------------
# Docs / Build
# ---------------------------------------------------------------------------

[doc("Build the documentation")]
[group("Docs")]
docs:
    moon run docs:build

[doc("Serve documentation locally for development")]
[group("Docs")]
docs-serve:
    moon run docs:serve

[doc("Build the production Docker image")]
[group("Build Docker")]
build:
    moon run root:image

# ---------------------------------------------------------------------------
# Production image (local, not moon-managed)
# ---------------------------------------------------------------------------

[doc("Build and initialize the production image locally")]
[group("Development")]
bootstrap:
    docker compose up --build --wait --detach
    docker compose exec imbi imbi-api setup

[doc("Destroy the local production-image environment")]
[group("Development")]
prod-teardown:
    docker compose down --remove-orphans --volumes
