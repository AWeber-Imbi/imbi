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

# Copy all service sources
COPY imbi-api/ imbi-api/
COPY imbi-plugin-aws/ imbi-plugin-aws/
COPY imbi-plugin-github/ imbi-plugin-github/
COPY imbi-plugin-logzio/ imbi-plugin-logzio/
COPY imbi-plugin-oidc/ imbi-plugin-oidc/
COPY imbi-assistant/ imbi-assistant/
COPY imbi-gateway/ imbi-gateway/
COPY imbi-mcp/ imbi-mcp/

# Build wheels for all services
RUN for svc in imbi-api imbi-plugin-aws imbi-plugin-github imbi-plugin-logzio imbi-plugin-oidc imbi-assistant imbi-gateway imbi-mcp; do \
  uv build /tmp/build/$svc --wheel --out-dir /tmp/wheels/; \
done

# Install all services into a venv, then clean up source
ENV UV_LINK_MODE=copy UV_PROJECT_DIRECTORY=/app VIRTUAL_ENV=/app
RUN uv venv --python $(which python3) $UV_PROJECT_DIRECTORY \
 && uv pip install --prerelease=allow /tmp/wheels/*.whl \
 && chmod -R a+rX /app

# ---------------------------------------------------------------------------
# Stage 3: Caddy binary
# ---------------------------------------------------------------------------
FROM caddy:${CADDY_VERSION} AS caddy

# ---------------------------------------------------------------------------
# Stage 4: Final runtime image
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

# Copy Caddyfile
COPY Caddyfile /etc/caddy/Caddyfile

# Copy UI static files
COPY --from=ui-builder /tmp/build/dist/ /srv/ui/

# Copy entrypoint
COPY --chmod=755 entrypoint.sh /usr/local/bin/entrypoint.sh

ENV PATH="/app/bin:$PATH"

EXPOSE 2019
EXPOSE 8080

USER imbi
WORKDIR /app

ENTRYPOINT ["tini", "--", "/usr/local/bin/entrypoint.sh"]
