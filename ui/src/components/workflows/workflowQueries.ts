import { queryOptions, useQuery } from '@tanstack/react-query'

import {
  getProjectsSlim,
  getWorkflow,
  getWorkflowRun,
  getWorkflowVersion,
  listAgents,
  listAIModels,
  listEnvironments,
  listIntegrations,
  listTeams,
  listWebhooks,
  listWorkflowOrgRuns,
  listWorkflowRuns,
  listWorkflows,
  listWorkflowStepChoices,
  listWorkflowStepTypes,
} from '@/api/endpoints'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'

import { isOpen } from './runs'
import { type FieldSource, hasTemplate } from './schemaFields'

/** How often an open run refreshes. Live views read Postgres (ADR 0021). */
const LIVE_MS = 2000
/** How often the runs of every workflow refresh while one is open. */
const LIST_MS = 15_000

/** The runs of every workflow of the org in the last `days` days.
 * Refreshes while one is open and not stuck. */
export function useOrgRuns(orgSlug: string | undefined, days: number) {
  const canRead = useHasPermission('workflow:read', orgSlug)
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => listWorkflowOrgRuns(orgSlug!, days, signal),
    queryKey: queryKeys.workflowOrgRuns(orgSlug ?? '', days),
    // A stuck run is open but does not change.
    refetchInterval: (query) =>
      query.state.data?.some((r) => isOpen(r.status) && !r.stuck)
        ? LIST_MS
        : false,
  })
}

/** Options for a live-data select, loaded only when a field needs them.
 * `plugin` limits integrations to those of a plugin with workflow steps. */
export function useSourceOptions(
  orgSlug: string,
  source: FieldSource,
  plugin?: string,
) {
  const models = useQuery({
    enabled: source === 'model',
    queryFn: ({ signal }) => listAIModels(signal),
    queryKey: queryKeys.aiModels(),
    // Model decisions take decision models only (ADR 0021).
    select: (rows) =>
      rows
        .filter((m) => m.enabled && m.model_type === 'decision')
        .map((m) => ({ label: m.name, value: m.id })),
  })
  const teams = useQuery({
    enabled: source === 'team',
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: queryKeys.teams(orgSlug),
    select: (rows) => rows.map((t) => ({ label: t.name, value: t.slug })),
  })
  const projects = useQuery({
    enabled: source === 'project',
    queryFn: ({ signal }) => getProjectsSlim(orgSlug, signal),
    queryKey: ['projects', orgSlug, 'slim'],
    select: (rows) => rows.map((p) => ({ label: p.name, value: p.id })),
  })
  const environments = useQuery({
    enabled: source === 'environment',
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: queryKeys.environments(orgSlug),
    select: (rows) => rows.map((e) => ({ label: e.name, value: e.slug })),
  })
  const webhooks = useQuery({
    enabled: source === 'webhook',
    queryFn: ({ signal }) => listWebhooks(orgSlug, signal),
    queryKey: ['webhooks', orgSlug],
    select: (rows) => rows.map((w) => ({ label: w.name, value: w.id })),
  })
  const agents = useQuery({
    enabled: source === 'agent',
    queryFn: ({ signal }) => listAgents(orgSlug, signal),
    queryKey: queryKeys.agents(orgSlug),
    select: (rows) => rows.map((a) => ({ label: a.name, value: a.id })),
  })
  const integrations = useQuery({
    enabled: source === 'integration',
    queryFn: ({ signal }) => listIntegrations(orgSlug, signal),
    queryKey: queryKeys.integrations(orgSlug),
    select: (rows) =>
      rows
        .filter(
          (i) =>
            i.plugin === plugin &&
            i.status !== 'inactive' &&
            i.capabilities?.['workflow-steps']?.enabled,
        )
        .map((i) => ({ label: i.name, value: i.slug })),
  })
  const query = {
    agent: agents,
    environment: environments,
    integration: integrations,
    model: models,
    project: projects,
    team: teams,
    webhook: webhooks,
  }[source]
  return { loading: query.isLoading, options: query.data ?? [] }
}

/**
 * The choices of a plugin step field (ADR 0032). `params` holds the
 * values of the fields that the choices depend on. No lookup while the
 * integration is unset or a value is a template: the plugin cannot read
 * them before the run.
 */
export function useStepChoices(
  orgSlug: string,
  integration: unknown,
  step: string,
  field: string,
  params: Record<string, unknown>,
) {
  const ready =
    typeof integration === 'string' &&
    integration !== '' &&
    !hasTemplate(integration) &&
    Object.values(params).every((v) => typeof v !== 'string' || !hasTemplate(v))
  return useQuery({
    enabled: ready,
    queryFn: ({ signal }) =>
      listWorkflowStepChoices(
        orgSlug,
        integration as string,
        step,
        { field, params },
        signal,
      ),
    queryKey: queryKeys.workflowStepChoices(
      orgSlug,
      integration,
      step,
      field,
      params,
    ),
    retry: false,
    select: (rows) => rows.map((c) => ({ label: c.label, value: c.value })),
    staleTime: 60_000,
  })
}

export function useStepTypes(orgSlug: string | undefined) {
  const canRead = useHasPermission('workflow:read', orgSlug)
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => listWorkflowStepTypes(orgSlug!, signal),
    queryKey: queryKeys.workflowStepTypes(orgSlug ?? ''),
    // Every step picker (palette, quick-add) lists steps A to Z.
    select: (types) =>
      [...types].sort((a, b) => a.label.localeCompare(b.label)),
    staleTime: 5 * 60_000,
  })
}

export function useWorkflow(orgSlug: string | undefined, slug: string) {
  const canRead = useHasPermission('workflow:read', orgSlug)
  return useQuery({
    enabled: !!orgSlug && canRead && slug !== 'new',
    queryFn: ({ signal }) => getWorkflow(orgSlug!, slug, signal),
    queryKey: queryKeys.workflow(orgSlug ?? '', slug),
  })
}

/** The workflows of an org. Disabled when the user may not read them. */
export function useWorkflowList(orgSlug: string | undefined) {
  const canRead = useHasPermission('workflow:read', orgSlug)
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => listWorkflows(orgSlug!, signal),
    queryKey: queryKeys.workflows(orgSlug ?? ''),
  })
}

/** One run with its steps. Refreshes while the run is open. */
export function useWorkflowRun(
  orgSlug: string,
  slug: string,
  runId: null | string,
) {
  return useQuery({
    enabled: !!runId,
    queryFn: ({ signal }) => getWorkflowRun(orgSlug, slug, runId!, signal),
    queryKey: queryKeys.workflowRun(orgSlug, slug, runId ?? ''),
    refetchInterval: (query) =>
      query.state.data && isOpen(query.state.data.status) ? LIVE_MS : false,
    // A run changes under the cache: read it again whenever it shows.
    staleTime: 0,
  })
}

/** The runs of a workflow, newest first. Refreshes while one is open. */
export function useWorkflowRuns(
  orgSlug: string,
  slug: string | undefined,
  enabled: boolean,
) {
  return useQuery({
    enabled: enabled && !!slug,
    queryFn: ({ signal }) => listWorkflowRuns(orgSlug, slug!, signal),
    queryKey: queryKeys.workflowRuns(orgSlug, slug ?? ''),
    refetchInterval: (query) =>
      query.state.data?.some((r) => isOpen(r.status)) ? LIVE_MS : false,
    staleTime: 0,
  })
}

/** One saved version. Disabled for ``null``. */
export function useWorkflowVersion(
  orgSlug: string,
  slug: string | undefined,
  version: null | number,
) {
  return useQuery({
    ...workflowVersionQuery(orgSlug, slug ?? '', version ?? 0),
    enabled: !!slug && version !== null,
  })
}

/** The query of one saved version, shared by the hook and `fetchQuery`. */
export function workflowVersionQuery(
  orgSlug: string,
  slug: string,
  version: number,
) {
  return queryOptions({
    queryFn: ({ signal }) => getWorkflowVersion(orgSlug, slug, version, signal),
    queryKey: [...queryKeys.workflow(orgSlug, slug), 'versions', version],
    // A version never changes.
    staleTime: Infinity,
  })
}
