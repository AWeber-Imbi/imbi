# Logging

Logging configuration management for consistent log formatting across
services.

## Overview

The logging module provides utilities to configure Python's logging system
using the bundled `log-config.toml` file. All Imbi services use the same
logging configuration for consistency.

## Basic Usage

```python
from imbi_common import logging

# Configure logging with bundled config
logging.configure_logging()

# Enable DEBUG level for development
logging.configure_logging(dev=True)

# Use custom config
custom_config = {
    "version": 1,
    "formatters": {
        "simple": {
            "format": "%(levelname)s: %(message)s"
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "simple"
        }
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"]
    }
}
logging.configure_logging(log_config=custom_config)
```

## Log Configuration

The bundled `log-config.toml` provides:
- Structured log formatting with timestamps
- Separate handlers for console and file output
- Appropriate log levels for different components
- Rotating file handlers with size limits

## Development Mode

When `dev=True` is passed to `configure_logging()`, all loggers under the
`imbi` namespace are automatically set to DEBUG level. This is useful for
local development.

## Access Log Middleware

`imbi_common.access_log.AccessLogMiddleware` is an ASGI middleware that
replaces uvicorn's built-in access log. It emits one record per HTTP
request on the `imbi_common.access` logger, in NCSA-style format with
the authenticated principal in the `authuser` slot.

```python
from fastapi import FastAPI
from imbi_common.access_log import AccessLogMiddleware

app = FastAPI()
app.add_middleware(
    AccessLogMiddleware,
    quiet_paths={'/status', '/health'},
)
```

### API key principals

JWT requests log the local part of the token subject. API key requests
(`Authorization: Bearer ik_<id>_<secret>`) log the opaque key id
(`ik_<id>`) by default, because the middleware runs synchronously in the
response path and can't resolve the owning user with an async database
lookup.

To log the human owner instead, register it from the consumer's API-key
authentication path with `remember_api_key_principal`:

```python
from imbi_common import access_log

# After validating ``ik_<id>_<secret>`` and loading the owning user:
access_log.remember_api_key_principal(key_id, user.email)
```

The label is cached (bounded LRU) keyed by `ik_<id>`, so once auth has
run for a request the access-log line — and every later line for that
key — renders the owner instead of the key id. Unregistered keys fall
back to `ik_<id>`; the request status still reflects whether validation
actually succeeded.

The rendered principal is escaped (`\r`/`\n` become literal backslash
sequences) before it is written to the log, so an attacker-controlled
label cannot forge additional log lines.

### Attaching per-request context

Handlers and downstream middleware can attach extra context to the
access-log line by writing a mapping to
`request.state.imbi_common_access_log`. Each entry is rendered as
`key:value` in a space-separated list wrapped in parentheses after the
status code:

```python
from fastapi import Request

@app.post('/events')
async def record_event(request: Request, event: Event) -> None:
    request.state.imbi_common_access_log = {
        'event_type': event.kind,
        'selected': event.selected,
    }
    ...
```

Produces a log line like:

```text
... "POST /events HTTP/1.1" 200 (event_type:whatever selected:False)
```

The suffix is omitted entirely when the mapping is missing or empty,
so existing log lines are unchanged for requests that don't opt in.
The `imbi_common_access_log` name is namespaced to avoid collisions
with other middleware that shares `request.state`.

### OpenTelemetry trace ID

When OpenTelemetry instrumentation is active and a valid server span
is recording the request, `AccessLogMiddleware` prepends
`trace_id:<32-char hex>` to the context suffix. The suffix renders
trace context and any handler-supplied context together, so a request
that sets per-handler context produces a log line like:

```text
... "POST /events HTTP/1.1" 200 (trace_id:cafebabe... event_type:x selected:False)
```

When no OpenTelemetry span is active (e.g. instrumentation is not
configured, the SDK is disabled, or the request was sampled out), the
`trace_id` field is omitted and the suffix only contains
handler-supplied context — preserving the existing format for
services that have not adopted OpenTelemetry.

Pass `include_trace_context=False` to the middleware to disable the
lookup entirely:

```python
app.add_middleware(
    AccessLogMiddleware,
    include_trace_context=False,
)
```

See [OpenTelemetry](otel.md) for the underlying
`current_trace_id()` helper and the related
`TraceIdResponseMiddleware`.

## API Reference

::: imbi_common.logging.get_log_config

::: imbi_common.logging.configure_logging

::: imbi_common.access_log.AccessLogMiddleware
