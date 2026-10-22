# Imbi Common Library

`imbi-common` is the shared library of the Imbi platform. It holds the
data access clients, the authentication code, the domain models, the
plugin contracts and the runtime helpers that every Imbi service uses.
It lives in the monorepo at `libraries/common` and is published to PyPI
as `imbi-common`.

## Consumers

Every service and every first-party plugin depends on `imbi-common`:

| Package | What it is |
|---|---|
| `imbi-api` | The API service |
| `imbi-assistant` | The AI assistant service |
| `imbi-gateway` | The webhook receiver |
| `imbi-harness` | The agent runner and executor |
| `imbi-mcp` | The MCP server |
| `imbi-scheduler` | The scheduled task service |
| `imbi-slackbot` | The Slack bot |
| `imbi-workflows` | The workflow engine |
| `imbi-plugin-*` | The first-party plugins (aws, github, google, logzio, oidc, pagerduty, sonarqube) |

For what each service does, see [Services](../architecture/services.md).

## Key Features

| Area | What the library gives you | Page |
|---|---|---|
| Graph | Apache AGE client with Cypher generation, vector search and embeddings | [Graph](api/graph.md) |
| Analytics | ClickHouse query client and the shared table schema | [ClickHouse](api/clickhouse.md) |
| Streaming | Apache Iggy publisher; the sink writes the rows to ClickHouse | [Iggy](api/iggy.md) |
| Cache | Valkey client | [Valkey](api/valkey.md) |
| Authentication | JWT tokens, encryption, password hashing | [Authentication](api/auth.md) |
| Authorization | Request authentication and permission checks | [Permissions](api/permissions.md) |
| Models | Pydantic domain models and the blueprint system | [Models](api/models.md), [Blueprints](api/blueprints.md) |
| Plugins | The plugin manifest, the capability contracts and the registry | [Authoring Plugins](plugins/index.md) |
| Prompts | Prompt CMS references, sandboxed rendering and render workers | [Prompts](api/prompts.md) |
| LLM | Anthropic JSON completions, provider drivers, model discovery | [LLM](api/llm.md) |
| Workflows | Workflow graph models, step types and validation | [Workflows](api/workflows.md) |
| MCP | Toolset policy for MCP servers made from the OpenAPI document | [MCP](api/mcp.md) |
| Observability | Logging, access log, OpenTelemetry, Prometheus metrics | [Logging](api/logging.md), [OpenTelemetry](api/otel.md), [Metrics](api/metrics.md) |
| Runtime | Settings, lifespan composition, the `serve` command | [Settings](api/settings.md), [Lifespan](api/lifespan.md) |

## Quick Links

- [Installation Guide](installation.md)
- [Quick Start](quickstart.md)
- [Configuration Reference](configuration.md)

## Package Layout

The main modules in `libraries/common/src/imbi/common/`:

```
imbi/common/
├── access_log.py    # ASGI access log middleware
├── auth/            # JWT, encryption, passwords, permissions
├── blueprints.py    # Dynamic schema system
├── clickhouse/      # ClickHouse client and schemata.toml
├── graph/           # Apache AGE client, embeddings, schemata.toml
├── iggy/            # Iggy publisher and TOPICS
├── lifespan.py      # Lifespan composition
├── llm/             # Anthropic client, drivers, discovery, TypeSafe
├── logging.py       # Logging configuration
├── mcp.py           # MCP toolset policy
├── metrics.py       # Prometheus /metrics route
├── models.py        # Domain models
├── otel.py          # OpenTelemetry setup
├── plugins/         # Plugin contracts and registry
├── prompts/         # Prompt CMS support
├── scoring/         # Project scoring engine
├── sentry.py        # Sentry lifespan hook
├── server.py        # Uvicorn serve command
├── settings.py      # Configuration management
├── valkey.py        # Valkey client
└── workflows/       # Workflow definitions
```

## Support

- [GitHub Issues](https://github.com/AWeber-Imbi/imbi/issues)

## License

BSD-3-Clause - See [LICENSE](https://github.com/AWeber-Imbi/imbi/blob/main/LICENSE) for details.
