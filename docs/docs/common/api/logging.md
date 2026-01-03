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

## API Reference

::: imbi_common.logging.get_log_config

::: imbi_common.logging.configure_logging
