# OpenTelemetry

Helpers for surfacing OpenTelemetry context on HTTP responses.

`imbi-common` does not configure the OpenTelemetry SDK itself —
that is the responsibility of the consuming service (see the
[Installation guide](../installation.md#opentelemetry) for the
recommended environment variables). The helpers in this module
operate on whatever span context is already active when the middleware
runs.

## Trace ID Response Middleware

`imbi_common.otel.TraceIdResponseMiddleware` is an ASGI middleware
that adds the active trace ID to every HTTP response. Operators and
frontend code can paste the value into the configured tracing backend
(Tempo, Jaeger, Honeycomb, etc.) to jump straight to the request's
trace.

```python
from fastapi import FastAPI
from imbi_common.otel import TraceIdResponseMiddleware

app = FastAPI()
app.add_middleware(TraceIdResponseMiddleware)
```

The default header name is `trace-id`. Override it when installing
the middleware — for example, to expose the trace ID under a
vendor-specific name:

```python
app.add_middleware(
    TraceIdResponseMiddleware, header_name='x-trace-id'
)
```

The header value is the 32-character lowercase hexadecimal trace ID
(the same format that appears in the W3C `traceparent` header).

### When the header is added

The middleware checks for a valid recording span on each request and
only writes the header when one is present. Specifically, no header
is added when:

- `opentelemetry-api` is not installed (the middleware is safe to
  install unconditionally — it becomes a pass-through).
- No OpenTelemetry instrumentation has activated a server span for
  the request (e.g. the SDK is disabled via `OTEL_SDK_DISABLED=true`,
  or the request was sampled out).
- The request is not an HTTP request (lifespan, WebSocket, etc.).

### Middleware ordering

Install `TraceIdResponseMiddleware` *outside* the OpenTelemetry
FastAPI/ASGI instrumentation so that the server span is active when
the response headers are written. In practice this means calling
`app.add_middleware(TraceIdResponseMiddleware)` *after* the
instrumentation has wrapped the application — Starlette's
`add_middleware` installs middleware in last-added-is-outermost
order, so the most-recently-added wrapper sees the response on its
way out.

### Standards note

There is no IANA-registered HTTP response header for tracing context.
The W3C `traceparent` and `tracestate` headers are scoped to request
direction; the W3C Trace Context Level 2 `traceresponse` header is an
unfinished draft. The pragmatic, standards-clean alternative for
browser clients is the IANA-registered
[`Server-Timing`](https://www.w3.org/TR/server-timing/) header
carrying a `traceparent` entry in addition to trace duration —
services that need browser-side correlation should expose the trace
ID through `Server-Timing` in addition to (or instead of) the
simple `trace-id` header.

## Trace ID Helper

`imbi_common.otel.current_trace_id()` returns the active span's trace
ID as a 32-character lowercase hexadecimal string, or `None` when no
valid OpenTelemetry span is recording (or `opentelemetry-api` is not
installed). Use it to correlate application logs, audit records, or
calls to external systems with a trace without depending directly on
the OpenTelemetry API:

```python
from imbi_common.otel import current_trace_id

trace_id = current_trace_id()
if trace_id is not None:
    audit_record.trace_id = trace_id
```

This is the same helper that `AccessLogMiddleware` and
`TraceIdResponseMiddleware` use internally.

## API Reference

::: imbi_common.otel.TraceIdResponseMiddleware

::: imbi_common.otel.current_trace_id
