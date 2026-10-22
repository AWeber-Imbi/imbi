# Imbi

Imbi is a DevOps service management platform for large environments with
many services and applications.

## What is Imbi?

- **A service catalog.** Imbi records each project, its type, its owner
  team, its links, its dependencies, and its documents, in a graph.
- **A delivery record.** Imbi records the commits, pull requests, tags,
  releases, and deployments of each project, and shows which environments
  run different code.
- **A quality check.** Imbi scores each project, checks it for problems
  (the Doctor), and records the components that each release ships.
- **An automation platform.** Imbi runs AI agents, workflows, and
  scheduled tasks against your projects, and connects to the tools you
  already use through plugins and webhooks.

## Key features

### Catalog

- **[Projects](user-guide/projects.md)**: one record for each service or
  application, with fields that [blueprints](admin/blueprints.md) define for
  each project type
- **[Organizations and teams](admin/users-teams-organizations.md)**: own
  the projects, with roles for each organization
- **[Documents](user-guide/documents-and-reports.md)**: versioned
  documents on projects, with read statistics
- **[Search and the assistant](user-guide/search-and-assistant.md)**:
  search the catalog from the top bar (Cmd+K) and ask the AI assistant

### Delivery

- **[Releases and deployments](user-guide/releases-and-deployments.md)**:
  deploy, promote a release to the next environment, block a release, and
  stop a deploy of a commit with failed CI
- **[Drift](user-guide/drift.md)**: see where environments run different
  code, and which commits are not released
- **[Pull requests and dependencies](user-guide/pull-requests-and-dependencies.md)**:
  pull request and commit history, and the software components of each
  release (SBOM)
- The data model is in [Delivery](architecture/delivery.md)

### Quality

- **[Doctor](user-guide/doctor.md)**: checks each project for problems and
  offers fixes
- **[Operations log and scoring](user-guide/operations-log-and-scoring.md)**:
  a record of changes, and a score for each project from
  [scoring policies](admin/scoring-policies.md)

### AI and automation

- **[Agents](admin/agents.md)** and **[agent tasks](admin/agent-tasks.md)**:
  AI agents that do work against your projects, in
  [runner pools](deployment/agent-runners.md) that you deploy
- **[Workflows](admin/workflows.md)**: deploy, rollback, agent, email,
  decision, and wait steps that start manually, on a schedule, or from a
  webhook
- **[Prompts](admin/prompts.md)**, **[AI models](admin/ai-models.md)**, and
  **[secrets](admin/secrets.md)**: versioned prompts, the model catalog of
  each organization, and short-lived secrets for agents
- **[Scheduler](scheduler/index.md)**: cron, interval, and one-shot
  triggers that call the API or the gateway
- **[MCP server](mcp/index.md)** and **[Slack bot](slackbot/index.md)**:
  use Imbi from MCP clients and from Slack

### Platform

- **[Integrations and plugins](admin/integrations-and-plugins.md)**:
  connect GitHub, PagerDuty, SonarQube, AWS, Logz.io, Google, and OIDC
  providers
- **[Webhook gateway](gateway/index.md)**: receive events and run actions
  from [webhook rules](admin/webhooks.md)
- **[Event pipeline](architecture/events.md)**: analytics rows go through
  Apache Iggy to ClickHouse
- **[Security](architecture/security.md)** and
  **[observability](architecture/overview.md#observability)**

## Architecture

The services are in one container image:

| Service | Purpose |
|---------|---------|
| **imbi-api** | The REST API, authentication, authorization, and the background workers |
| **imbi-assistant** | The AI assistant in the UI |
| **imbi-gateway** | Receives webhooks and runs plugin actions |
| **imbi-mcp** | The MCP server for AI agents and MCP clients |
| **imbi-scheduler** | Fires scheduled tasks against imbi-api and imbi-gateway |
| **imbi-slackbot** | The Slack bot |
| **imbi-workflows** | The workflow engine |
| **Caddy and the UI** | The reverse proxy, and the static files of the React UI |

Caddy is the only public port. imbi-slackbot connects out to Slack in
socket mode, and imbi-workflows has no public route.

These parts are not in the image:

- **imbi-harness**, the agent runner, has its own image and Helm chart.
  See [Agent Runners](deployment/agent-runners.md).
- **iggy-connect** runs from the Apache Iggy image as a separate container.
  It writes the analytics rows to ClickHouse.

See the [architecture overview](architecture/overview.md).

## Data stores

| Store | Required | Purpose |
|-------|----------|---------|
| **PostgreSQL + Apache AGE** | Yes | The graph of the catalog, and the relational schemas of agent tasks, workflows, secrets, runner pools, and the scheduler |
| **ClickHouse** | Yes | Analytics: the operations log, events, commits, pull requests, scores, drift verdicts, runs, and audit trails |
| **Apache Iggy** | Yes | Message streams. Every ClickHouse row goes through Iggy, and iggy-connect writes it to ClickHouse |
| **S3-compatible storage** | Yes | Uploaded files |
| **Valkey** | For background work | The work queues of the imbi-api background workers (syncs, scoring, maintenance) |
| **SMTP server** | For email | Welcome and password reset email, and workflow email steps. Email is on by default |
