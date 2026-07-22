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

RUN pip install uv \
 && apt update \
 && apt install -y --no-install-recommends git \
 && apt install -y gcc

# Build a wheel for every workspace member plus the imbi meta-package
COPY pyproject.toml uv.lock README.md LICENSE /tmp/build/
COPY libraries/ /tmp/build/libraries/
COPY apps/ /tmp/build/apps/
COPY plugins/ /tmp/build/plugins/
RUN uv build /tmp/build --all-packages --wheel --out-dir /tmp/wheels/

# Install every wheel into a venv
ENV UV_LINK_MODE=copy UV_PROJECT_DIRECTORY=/app VIRTUAL_ENV=/app
RUN uv venv --python $(which python3) $UV_PROJECT_DIRECTORY \
 && uv pip install --prerelease=allow /tmp/wheels/*.whl \
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
 && apt install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

# Create imbi user
RUN useradd -r -g users -d /app imbi

# Copy Python venv with all services installed
COPY --from=python-builder --chown=imbi:users /app/ /app/

# Copy Caddy binary
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy

# Copy Sentry CLI binary
COPY --from=sentry-cli /bin/sentry-cli /usr/local/bin/sentry-cli

# Copy Caddyfile
COPY container/Caddyfile /etc/caddy/Caddyfile

# Copy UI static files
COPY --from=ui-builder /tmp/build/dist/ /srv/ui/

# Copy entrypoint
COPY --chmod=755 container/entrypoint.sh /usr/local/bin/entrypoint.sh

ENV PATH="/app/bin:$PATH"

# Caddy Admin
EXPOSE 2019

# Caddy Public Port
EXPOSE 8080

USER imbi
WORKDIR /app

ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
