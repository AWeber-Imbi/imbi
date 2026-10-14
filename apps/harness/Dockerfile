# The runner pod image (ADR 0022). Build from the repository root:
#   docker build -f apps/harness/Dockerfile --target runtime .
# The isolation target adds the P5a test suite and stub.
ARG PYTHON_VERSION=3.14

FROM python:${PYTHON_VERSION}-slim AS builder

RUN pip install --no-cache-dir uv
WORKDIR /src
# uv needs every workspace member to read the lock file.
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY libraries/ libraries/
COPY apps/ apps/
COPY plugins/ plugins/
ENV UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/app UV_PYTHON_DOWNLOADS=never
RUN uv sync --frozen --no-dev --no-editable --package imbi-harness

FROM python:${PYTHON_VERSION}-slim AS runtime

# git clones the workspace; gh is the model's GitHub client (H19).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates gh git tini \
 && rm -rf /var/lib/apt/lists/*

# Only runner and executor are in harness-ipc, the group of the
# executor socket.
RUN groupadd -g 10010 harness-ipc \
 && groupadd -g 10001 runner \
 && useradd -u 10001 -g runner -G harness-ipc -M -d /nonexistent -s /usr/sbin/nologin runner \
 && groupadd -g 10002 executor \
 && useradd -u 10002 -g executor -G harness-ipc -M -d /nonexistent -s /usr/sbin/nologin executor \
 && groupadd -g 10003 agent \
 && useradd -u 10003 -g agent -M -d /work -s /bin/sh agent

COPY --from=builder /app /app
COPY --chmod=0755 apps/harness/agent-cli /usr/local/bin/agent-cli
COPY --chmod=0755 apps/harness/git-credential-fd /usr/local/libexec/git-credential-fd
RUN mkdir -p /usr/local/libexec /work /run/creds /run/executor \
 && ln -s "$(/app/bin/python -c 'import claude_agent_sdk, pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")')" /usr/local/libexec/claude \
 && chown agent:agent /work \
 && find / -xdev -perm /6000 -type f -exec chmod a-s {} +

ENV PATH="/app/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
ENTRYPOINT ["tini", "--", "imbi-harness"]

FROM runtime AS isolation
COPY apps/harness/isolation/ /opt/isolation/
