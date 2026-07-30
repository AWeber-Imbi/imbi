# Imbi Scheduler

Triggers remote execution on a schedule. The scheduler fires cron, interval,
calendar, and one-shot triggers, then makes a single HTTP request per run — to
`imbi-api` as a named principal, or to `imbi-gateway` as a webhook delivery. It
does not execute the work itself; it triggers whichever service owns it.

Task definitions and trigger state live in the `scheduler` Postgres schema; run
history lives in ClickHouse (`imbi.scheduler_runs`).

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
moon run scheduler:lint scheduler:typecheck scheduler:format   # Check for lint errors
```

The formatters use complex, nuanced rules (line length, quote style, etc.) that are configured in `pyproject.toml` and `.pre-commit-config.yaml`. See `AGENTS.md` for complete details.
