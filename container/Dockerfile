ARG PYTHON_VERSION=3.14
ARG CADDY_VERSION=2
ARG NODE_VERSION=24

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
 && apt install -y --no-install-recommends tini libcap2-bin \
 && rm -rf /var/lib/apt/lists/*

# The base image's pip ships in the image: use one whose CA bundle does
# not trust the eMudhra root.
RUN pip install --no-cache-dir --upgrade 'pip>=26.2.2'

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
