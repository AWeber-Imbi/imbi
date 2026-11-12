ARG PYTHON_VERSION=3.14
ARG CADDY_VERSION=2
ARG NODE_VERSION=24

# ---------------------------------------------------------------------------
# Stage 0: PostHog CLI binary (UI source maps)
# ---------------------------------------------------------------------------
# A static musl build from the GitHub release, checked against the SHA-256
# that the release publishes. To upgrade, change the version and both
# checksums together.
FROM python:${PYTHON_VERSION}-slim AS posthog-cli
ARG TARGETARCH
RUN set -eu; \
    case "$TARGETARCH" in \
      amd64) target=x86_64-unknown-linux-musl; \
             sha=5227b8e00a463ea42e09cd77e2f8cfd9bf6f4c4af6fbe0d2522fcd0dc99b93f5 ;; \
      arm64) target=aarch64-unknown-linux-musl; \
             sha=533e56f8a892997d89c993da72c789fbe212063584c46d448fb368d7ac0d878d ;; \
      *) echo "unsupported TARGETARCH: $TARGETARCH" >&2; exit 1 ;; \
    esac; \
    python3 -c 'import sys, urllib.request; urllib.request.urlretrieve(sys.argv[1], "/tmp/cli.tgz")' \
      "https://github.com/PostHog/posthog/releases/download/posthog-cli/v0.19.0/posthog-cli-$target.tar.gz"; \
    echo "$sha  /tmp/cli.tgz" | sha256sum -c -; \
    tar -xzf /tmp/cli.tgz -C /tmp; \
    install -m 755 "/tmp/posthog-cli-$target/posthog-cli" /usr/local/bin/posthog-cli

# ---------------------------------------------------------------------------
# Stage 1: Build the UI
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-slim AS ui-builder

WORKDIR /tmp/build
ARG VITE_GIT_REF=""
ENV VITE_GIT_REF=${VITE_GIT_REF}
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ ./
ENV NODE_OPTIONS="--max-old-space-size=4096"
RUN npm run build
# Write a chunk id into each bundle and its source map, so PostHog can match
# a stack frame to an uploaded map. The upload runs when the container
# starts (entrypoint.sh). Only assets/ holds bundles; the service worker and
# index.html stay as built.
#
# Inject works offline here: the build context has no .git and no release
# flags, so the CLI resolves no release and calls no API. The CLI still
# insists on credentials and starts a client that sends its own usage
# telemetry to PostHog, so the step gets placeholder credentials (never
# sent), a CA bundle for that client to start, and --network=none so
# nothing leaves the build.
# ponytail: placeholder credentials; drop them when posthog-cli lets inject
# run without credentials.
COPY --from=posthog-cli /usr/local/bin/posthog-cli /usr/local/bin/posthog-cli
COPY --from=posthog-cli /etc/ssl/certs/ca-certificates.crt /tmp/ca-certificates.crt
RUN --network=none \
    SSL_CERT_FILE=/tmp/ca-certificates.crt \
    POSTHOG_CLI_API_KEY=phx_offline_inject POSTHOG_CLI_PROJECT_ID=0 \
    posthog-cli sourcemap inject --directory dist/assets

# ---------------------------------------------------------------------------
# Stage 2: Build all Python services
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS python-builder

WORKDIR /tmp/build

# pip 26.2.2 and uv 0.13.5 drop the eMudhra root from their bundled CA
# stores (key compromise, 2026-10-19); uv downloads every dependency.
RUN pip install --upgrade 'pip>=26.2.2' 'uv>=0.13.5' \
 && apt update \
 && apt install -y --no-install-recommends git curl \
 && apt install -y gcc

# `apache-iggy` publishes wheels for CPython 3.10 to 3.13 only, so on 3.14
# its sdist is compiled here. Rust lands in this stage alone; the runtime
# stage copies only the resulting venv.
RUN curl -fsS https://sh.rustup.rs | sh -s -- -y --profile minimal
ENV PATH="/root/.cargo/bin:$PATH"
# The sdist makes some lints errors, so a lint that a new stable Rust
# adds (such as a new deprecation) stops the build. Cap all lints at
# warnings.
ENV RUSTFLAGS="--cap-lints=warn"

# Install the imbi meta-package and every workspace member it depends on
# into a venv, at the versions in uv.lock. The meta-package does not
# depend on imbi-harness, which has its own image (apps/harness/Dockerfile).
COPY pyproject.toml uv.lock README.md LICENSE /tmp/build/
COPY libraries/ /tmp/build/libraries/
COPY apps/ /tmp/build/apps/
COPY plugins/ /tmp/build/plugins/
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app UV_PYTHON_DOWNLOADS=never
RUN uv sync --frozen --no-dev --no-editable \
 && chmod -R a+rX /app

# ---------------------------------------------------------------------------
# Stage 3: Caddy binary
# ---------------------------------------------------------------------------
FROM caddy:${CADDY_VERSION} AS caddy

# ---------------------------------------------------------------------------
# Stage 4: Sentry CLI binary
# ---------------------------------------------------------------------------
FROM getsentry/sentry-cli AS sentry-cli

# ---------------------------------------------------------------------------
# Stage 5: Final runtime image
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

# Install runtime dependencies
RUN apt update \
 && apt install -y --no-install-recommends ca-certificates tini libcap2-bin \
 && rm -rf /var/lib/apt/lists/*

# The base image's pip ships in the image: use one whose CA bundle does
# not trust the eMudhra root.
RUN pip install --no-cache-dir --upgrade 'pip>=26.2.2'

# ssl.create_default_context() (SMTP, settings CA paths) uses the Debian
# store. Debian 13 still trusts the two eMudhra roots that Mozilla removed
# after the 2026-10-19 key compromise, so deselect them, as certifi and uv
# do. A no-op once Debian ships the removal; the check fails the build if
# either root is still trusted.
RUN sed -i -E 's#^(mozilla/emSign_(Root_CA_-_C1|ECC_Root_CA_-_C3)\.crt)$#!\1#' \
      /etc/ca-certificates.conf \
 && update-ca-certificates --fresh \
 && ! ls /etc/ssl/certs | grep -E 'emSign_(Root_CA_-_C1|ECC_Root_CA_-_C3)'

# Create imbi user
RUN useradd -r -g users -d /app imbi

# Copy Python venv with all services installed
COPY --from=python-builder --chown=imbi:users /app/ /app/

# Copy Caddy binary. COPY keeps the CAP_NET_BIND_SERVICE file capability
# from the caddy image, and the kernel refuses to exec a binary with file
# capabilities when privilege escalation is disabled (Kubernetes
# allowPrivilegeEscalation=false). caddy listens on 8080, so drop it.
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy
RUN setcap -r /usr/local/bin/caddy

# Copy Sentry CLI binary
COPY --from=sentry-cli /bin/sentry-cli /usr/local/bin/sentry-cli

# Copy PostHog CLI binary
COPY --from=posthog-cli /usr/local/bin/posthog-cli /usr/local/bin/posthog-cli

# Copy Caddyfile
COPY container/Caddyfile /etc/caddy/Caddyfile

# Copy UI static files
COPY --from=ui-builder /tmp/build/dist/ /srv/ui/

# Copy entrypoint
COPY --chmod=755 container/entrypoint.sh /usr/local/bin/entrypoint.sh

ENV PATH="/app/bin:$PATH"

# Caddy Public Port
EXPOSE 8080

USER imbi
WORKDIR /app

ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
