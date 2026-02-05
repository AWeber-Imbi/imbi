FROM python:3.14-slim AS builder

WORKDIR /tmp/install

RUN pip install uv \
 && apt update \
 && apt install git --yes

COPY dist/*.whl pyproject.toml uv.lock /tmp/install/

RUN uv venv /app \
 && . /app/bin/activate \
 && uv sync --no-dev --active --frozen --no-install-project \
 && uv pip install *.whl

FROM python:3.14-slim AS service
EXPOSE 8000
ENV PATH="/app/bin:$PATH"
WORKDIR /app
COPY --from=builder /app/ /app/
CMD ["/app/bin/imbi-gateway", "serve", "--host", "0.0.0.0"]
