# Imbi Gateway

Inbound webhook gateway service that receives external events, records them, and routes them through a workflow engine for processing. Acts as the central integration point between external systems and internal services like imbi-automations.

## Developer Quickstart

This project uses [uv](https://docs.astral.sh/uv/) for project management and [just](https://just.systems/man/en/) as a task runner. You need to install both before you can contribute changes.

```shell
just setup
```

Run `just -l` for the available commands.
