import { useQuery } from '@tanstack/react-query'

import {
  getProjectsSlim,
  getWorkflow,
  getWorkflowRun,
  listAIModels,
  listEnvironments,
  listTeams,
  listWebhooks,
  listWorkflowAttention,
  listWorkflowRuns,
  listWorkflows,
  listWorkflowStepTypes,
} from '@/api/endpoints'
import { useAuth } from '@/hooks/useAuth'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'

import { isOpen } from './runs'
import type { FieldSource } from './schemaFields'

/** How often an open run refreshes. Live views read Postgres (ADR 0021). */
const LIVE_MS = 2000

/** Options for a live-data select, loaded only when a field needs them. */
export function useSourceOptions(orgSlug: string, source: FieldSource) {
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
  const query = {
    environment: environments,
    model: models,
    project: projects,
    team: teams,
    webhook: webhooks,
  }[source]
  return { loading: query.isLoading, options: query.data ?? [] }
}

export function useStepTypes(orgSlug: string | undefined) {
  const canRead = useHasPermission('workflow:read')
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => listWorkflowStepTypes(orgSlug!, signal),
    queryKey: queryKeys.workflowStepTypes(orgSlug ?? ''),
    staleTime: 5 * 60_000,
  })
}

export function useWorkflow(orgSlug: string | undefined, slug: string) {
  const canRead = useHasPermission('workflow:read')
  return useQuery({
    enabled: !!orgSlug && canRead && slug !== 'new',
    queryFn: ({ signal }) => getWorkflow(orgSlug!, slug, signal),
    queryKey: queryKeys.workflow(orgSlug ?? '', slug),
  })
}

/** Failed and stuck runs of the org. Loaded for admins only. */
export function useWorkflowAttention(orgSlug: string | undefined) {
  const { user } = useAuth()
  return useQuery({
    enabled: !!orgSlug && !!user?.is_admin,
    queryFn: ({ signal }) => listWorkflowAttention(orgSlug!, signal),
    queryKey: queryKeys.workflowAttention(orgSlug ?? ''),
  })
}

/** The workflows of an org. Disabled when the user may not read them. */
export function useWorkflowList(orgSlug: string | undefined) {
  const canRead = useHasPermission('workflow:read')
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
