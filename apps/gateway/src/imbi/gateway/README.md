# Imbi Gateway

Inbound webhook gateway service that receives external events, records them, and routes them through a workflow engine for processing. Acts as the central integration point between external systems and internal services like imbi-automations.

## Developer Quickstart

This project uses [uv](https://docs.astral.sh/uv/) for project management and [moon](https://moonrepo.dev) as its task runner. Install moon before you can contribute changes.

```shell
moon run root:setup
```

Run `moon query tasks` for the available commands.

## Code Formatting

This project uses automated formatting tools that are the sole authority on code style:

- **Ruff** for Python code (formatting and linting)
- **Tombi** for TOML files
- **Pre-commit hooks** to run formatters automatically on commit

**Do not manually format code.** Instead, use:

```bash
uv run pre-commit run --all-files          # Format all files
uv run pre-commit run --files src/app.py   # Format a specific file
moon run gateway:lint gateway:typecheck gateway:format   # Check for lint errors
```

The formatters use complex, nuanced rules (line length, quote style, etc.) that are configured in `pyproject.toml` and `.pre-commit-config.yaml`. See `AGENTS.md` for complete details.
