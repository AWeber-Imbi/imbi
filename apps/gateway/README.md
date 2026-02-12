# Imbi Gateway

Inbound webhook gateway service that receives external events, records them, and routes them through a workflow engine for processing. Acts as the central integration point between external systems and internal services like imbi-automations.

## Developer Quickstart

This project uses [uv](https://docs.astral.sh/uv/) for project management and [just](https://just.systems/man/en/) as a task runner. You need to install both before you can contribute changes.

```shell
just setup
```

Run `just -l` for the available commands.

## Code Formatting

This project uses automated formatting tools that are the sole authority on code style:

- **Ruff** for Python code (formatting and linting)
- **Tombi** for TOML files
- **Pre-commit hooks** to run formatters automatically on commit

**Do not manually format code.** Instead, use:

```bash
just format              # Format all files
just format src/app.py   # Format a specific file
just lint                # Check for linting errors
```

The formatters use complex, nuanced rules (line length, quote style, etc.) that are configured in `pyproject.toml` and `.pre-commit-config.yaml`. See `AGENTS.md` for complete details.
