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

## API Reference

::: imbi_common.logging.get_log_config

::: imbi_common.logging.configure_logging

::: imbi_common.access_log.AccessLogMiddleware
