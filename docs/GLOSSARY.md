# Imbi

Imbi records who owns each project, where it runs and how healthy it is, and it runs the agents and workflows that keep projects in shape.

## Organizations and projects

**Organization**:
The top-level tenant. Teams, projects, environments, integrations, agents and workflows each belong to one organization.
_Avoid_: tenant

**Team**:
A group of people in an organization that owns projects, agents and workflows.

**Project**:
One thing a team builds and runs, such as a service, library, site or job.

**Project Type**:
A classification of projects that decides which blueprints, scoring policies and delivery mode apply. A project can have more than one.

**Environment**:
A place where projects run, such as Testing, Staging or Production. Environments are ordered, and the order is the path work takes toward production.

**Terminal Environment**:
An environment marked as the end of the environment order, usually Production. Work counts as shipped once it reaches one.

**Blueprint**:
An admin-defined schema that adds custom fields to a kind of entity, such as projects, tickets or deployments, or to a relationship between two kinds.

## Delivery

**Delivery Mode**:
How Imbi ships a project: deployable (to environments), releasable (as tagged releases only) or disabled. It comes from the project type and can be overridden per project.

**Release**:
A tagged version of a project, with release notes. A release is cut, can be blocked, and is deployed to environments.

**Release Notes**:
The human-editable description of what changed in a release.

**Tag Format**:
The allowed pattern for new release tags: semantic, calendar, git short SHA or any.

**Blocker**:
A record that stops a release from being deployed, promoted or published until someone resolves it.

**Deployment**:
One rollout of a project's release or commit into one environment.

**Rollback**:
Redeploying an earlier release or commit to an environment.

**Drift**:
Changes that exist but have not shipped yet. Imbi tracks drift between adjacent environments, between a project's latest release and newer commits, and on a release's own commit.

**Drift Verdict**:
CI's per-commit answer to whether a commit is drift. A range of commits counts as proven clean only when every commit in it has a "no drift" verdict.

**Pull Request**:
A proposed change on a code host, synced into Imbi. Imbi uses this name for every code host's equivalent.
_Avoid_: merge request, change request

**SBOM**:
The software bill of materials Imbi ingests for a release, in CycloneDX format, listing the third-party software the release includes.

## Health

**Scoring Policy**:
An admin-defined rule that rates one aspect of a project from 0 to 100 and carries a weight. A project's score is the weighted average of the policies that apply to it.

**Operations Log**:
The human-readable record of operational changes to projects, such as deployments, restarts and migrations.

**Maintenance Operation**:
An admin-run job that acts across every project at once, such as applying sync fixes or reindexing search.

## Integrations

**Plugin**:
An installable package that connects Imbi to an external platform, such as GitHub, AWS or PagerDuty, and offers capabilities.

**Integration**:
A configured instance of a plugin, with its own options and credentials. One plugin can back many integrations.
_Avoid_: third-party service, service application

**Capability**:
One kind of work a plugin offers through an integration, such as deployment, logs or identity. Each capability is turned on per integration.
_Avoid_: plugin type

**Identity Connection**:
A person's link to their own account on an external platform, through one integration, so Imbi can act as them there.
_Avoid_: OAuth identity

**Webhook**:
An inbound endpoint that receives notifications from one integration.

**Webhook Rule**:
A filter and an action that Imbi runs, in order, on each request a webhook receives.

## Tickets and agents

**Ticket**:
A tracked item of work assigned to an agent or a person. It keeps its identity as it passes between assignees, and it can be reopened after it closes.
_Avoid_: agent task, task

**Agent Ticket**:
A ticket whose assignee is an agent.

**Person Ticket**:
A ticket whose assignee is a person.

**Assignee**:
The agent or person currently working a ticket.

**Handoff**:
Moving a ticket from an agent to a person, or from a person to an agent. Moving a ticket from one person to another is not a handoff.

**Agent**:
An organization's configured AI worker, with an owner team, model, prompt, tools and limits.

**Agent Version**:
An immutable snapshot of an agent's configuration, saved on each change. A ticket keeps the version that was current when it was created.

**Runner**:
A worker that executes agent tickets.

**Runner Pool**:
A platform-managed group of runners that serves one or more organizations.

## Workflows

**Workflow**:
A versioned graph of steps, owned by an organization, that Imbi runs each time its trigger fires.

**Workflow Version**:
An immutable saved revision of a workflow. Only the active version runs.

**Workflow Run**:
One execution of a workflow's active version.

## Secrets

**Secret Provider**:
An organization's connection to an external secret store. Imbi reads secrets through it and stores none itself.

**Secret Binding**:
A named `secret://` reference to one secret at a secret provider.

**Secret Grant**:
Permission for specific agents and projects to resolve specific secret bindings for stated purposes.

**Secret Resolution**:
One short-lived issuance of a secret to a ticket on a runner. It can be released or revoked.

## AI

**AI Provider**:
A configured, credentialed account with an LLM vendor.

**AI Model**:
A model in Imbi's catalog, served by an AI provider, with its price and the teams allowed to use it.

**Generative Model**:
An AI model that returns text.

**Decision Model**:
An AI model that returns probabilities over a fixed set of choices. Workflows use it to pick a branch.

**Prompt**:
A versioned template in Imbi's prompt library.

**Prompt Label**:
A named pointer, such as `stable`, to one version of a prompt.

**Assistant**:
The chat interface that answers questions and acts in Imbi as the signed-in person.

## Access

**Service Account**:
A non-human principal used for automation. Each agent acts as its own service account.

## Documents

**Document**:
Markdown content attached to a project, a project type or a person, with versions and comments.

**Document Template**:
Starter content for new documents.
