ARG PYTHON_VERSION=3.14
ARG CADDY_VERSION=2
ARG NODE_VERSION=22

# ---------------------------------------------------------------------------
# Stage 1: Build the UI
# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-slim AS ui-builder

WORKDIR /tmp/build
COPY imbi-ui/package.json imbi-ui/package-lock.json ./
RUN npm ci
COPY imbi-ui/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: Build all Python services
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS python-builder

WORKDIR /tmp/build

RUN pip install uv \
 && apt-get update \
 && apt-get install -y --no-install-recommends git \
 && rm -rf /var/lib/apt/lists/*

# Build imbi-common first (dependency of other services)
COPY imbi-common/pyproject.toml imbi-common/uv.lock imbi-common/
COPY imbi-common/src/ imbi-common/src/
RUN cd imbi-common && uv build --wheel --out-dir /tmp/wheels/

# Build imbi-api
COPY imbi-api/pyproject.toml imbi-api/uv.lock imbi-api/
COPY imbi-api/src/ imbi-api/src/
RUN cd imbi-api && uv build --wheel --out-dir /tmp/wheels/

# Build imbi-assistant
COPY imbi-assistant/pyproject.toml imbi-assistant/uv.lock imbi-assistant/
COPY imbi-assistant/src/ imbi-assistant/src/
RUN cd imbi-assistant && uv build --wheel --out-dir /tmp/wheels/

# Build imbi-gateway
COPY imbi-gateway/pyproject.toml imbi-gateway/uv.lock imbi-gateway/
COPY imbi-gateway/src/ imbi-gateway/src/
RUN cd imbi-gateway && uv build --wheel --out-dir /tmp/wheels/

# Build imbi-mcp
COPY imbi-mcp/pyproject.toml imbi-mcp/uv.lock imbi-mcp/
COPY imbi-mcp/src/ imbi-mcp/src/
RUN cd imbi-mcp && uv build --wheel --out-dir /tmp/wheels/

# Install all services into a venv
RUN uv venv /app \
 && . /app/bin/activate \
 && uv pip install /tmp/wheels/*.whl

# ---------------------------------------------------------------------------
# Stage 3: Caddy binary
# ---------------------------------------------------------------------------
FROM caddy:${CADDY_VERSION} AS caddy

# ---------------------------------------------------------------------------
# Stage 4: Final runtime image
# ---------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS runtime

# Install runtime dependencies
RUN apt-get update \
 && apt-get install -y --no-install-recommends tini \
 && rm -rf /var/lib/apt/lists/*

# Create imbi user
RUN useradd -r -g users -d /app imbi

# Copy Python venv with all services installed
COPY --from=python-builder /app/ /app/

# Copy Caddy binary
COPY --from=caddy /usr/bin/caddy /usr/local/bin/caddy

# Copy Caddyfile
COPY Caddyfile /etc/caddy/Caddyfile

# Copy UI static files
COPY --from=ui-builder /tmp/build/dist/ /srv/ui/

# Copy entrypoint
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

ENV PATH="/app/bin:$PATH"

EXPOSE 8080

USER imbi
WORKDIR /app

ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
