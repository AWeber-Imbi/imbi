# Settings

The settings module provides type-safe configuration management using Pydantic Settings.

## Overview

Configuration is loaded from multiple sources in priority order:
1. Environment variables (highest priority)
2. `./config.toml` (project directory)
3. `~/.config/imbi/config.toml` (user directory)
4. `/etc/imbi/config.toml` (system directory)
5. Built-in defaults (lowest priority)

## Loading Configuration

```python
from imbi_common import settings

# Load full configuration
config = settings.load_config()

# Access individual settings sections
neo4j_config = settings.Neo4j()
clickhouse_config = settings.Clickhouse()
auth_config = settings.Auth()
```

## API Reference

::: imbi_common.settings.load_config

::: imbi_common.settings.get_auth_settings

::: imbi_common.settings.Configuration

::: imbi_common.settings.Neo4j

::: imbi_common.settings.Clickhouse

::: imbi_common.settings.ServerConfig

::: imbi_common.settings.Auth

::: imbi_common.settings.Email
