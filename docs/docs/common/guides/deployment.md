# Deployment Guide

The `imbi_common.server` module provides a reusable function for starting a uvicorn server instance. This allows
you to create a consistent server startup command across multiple Imbi ecosystem services without duplicating
uvicorn configuration code.

## Installation

Include the `server` extra when installing imbi-common to get uvicorn and its dependencies:

```bash
pip install imbi-common[server]
# or with uv
uv add imbi-common[server]
```

## Command Reference

Once integrated into your CLI, the serve command will have the following signature:

```text
your-cli serve [OPTIONS] ENTRYPOINT

Options:
  --dev                   Enable development mode (auto-reload, debug logging)
  --env-file PATH         Load environment variables from .env file
  --log-config PATH       Path to custom TOML logging configuration
  --host TEXT             IP or hostname to bind to (default: 127.0.0.1)
  --port INTEGER          Port to bind to (default: 8000)
  --verbose               Enable DEBUG logging for the application
  --help                  Show this message and exit
```

## Usage

### Basic Integration

Add `imbi_common.server.serve` as a command to your own [Typer](https://typer.tiangolo.com/)-based CLI:

```python
import typer
from imbi_common import server

cli = typer.Typer()
cli.command('serve')(server.serve)

if __name__ == '__main__':
    cli()
```

Users would then run your application like:

```bash
your-cli serve my_package.api:create_app
```

### Advanced: Pre-binding the Entrypoint

If you want to hardcode the entrypoint so users don't need to specify it, use `server.bind_entrypoint()`:

```python
import typer
from imbi_common import server

cli = typer.Typer()
cli.command('serve')(
    server.bind_entrypoint('my_package.api:create_app')
)
```

Users can then start the server without specifying the entrypoint:

```bash
your-cli serve --dev --port 8080
```

## Entrypoint Format

The entrypoint must be formatted as `module_name:factory_name`:

- `module_name`: Dotted Python path to the module (e.g., `my_package.api`)
- `factory_name`: Name of the factory function (e.g., `create_app`)

The factory function must return a FastAPI application instance. The entrypoint's package name (first component before
the dot) is used to configure logging when `--dev` or `--verbose` is enabled.

## Environment Variables

### Loading from .env Files

The `--env-file` flag loads environment variables from a file before starting your application:

```bash
your-cli serve --env-file .env.local my_package.api:create_app
```

!!! warning "Uvicorn Environment Variables"
    The `.env` file is loaded by uvicorn **after** it starts but **before** your application factory is called.

    - ✅ Your application **can** access variables from the `.env` file
    - ❌ Uvicorn **cannot** access variables from the `.env` file

    To configure uvicorn itself, set `UVICORN_` prefixed environment variables in your shell before running the command.

### Uvicorn Environment Variables

Uvicorn supports many environment variables for configuration. See the [Uvicorn settings documentation](https://www.uvicorn.org/settings/)
for a complete list. Common examples include:

- `UVICORN_HOST`: Override the host binding
- `UVICORN_PORT`: Override the port binding
- `UVICORN_LOG_LEVEL`: Set uvicorn's own log level

## Logging Configuration

### Development Mode (`--dev`)

Enables comprehensive debugging for local development:

- **Auto-reload**: Server restarts when code changes are detected
- **Application logging**: Sets your application's log level to `DEBUG`
- **imbi-common logging**: Sets imbi-common's log level to `DEBUG`
- **Uvicorn logging**: Sets uvicorn's log level to `TRACE` (very verbose)

Equivalent to setting:
```bash
UVICORN_LOG_LEVEL=trace UVICORN_RELOAD=true
```

!!! warning
    Do not use `--dev` in production. The auto-reload feature watches the filesystem and can impact performance.

### Verbose Mode (`--verbose`)

Enables debug logging for your application only:

- **Application logging**: Sets your application's log level to `DEBUG`
- **Uvicorn logging**: Remains at default level (`INFO`)

Use this in production when you need detailed application logs without uvicorn's internal trace logging.

### Custom Logging Configuration

Provide a custom TOML logging configuration file:

```bash
your-cli serve --log-config logging.toml my_package.api:create_app
```

The TOML file should follow Python's [logging configuration dictionary schema](https://docs.python.org/3/library/logging.config.html#dictionary-schema-details). If not provided, imbi-common uses a sensible default configuration.
