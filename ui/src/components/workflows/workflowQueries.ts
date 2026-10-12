import { useQuery } from '@tanstack/react-query'

import {
  getProjectsSlim,
  getWorkflow,
  listAIModels,
  listEnvironments,
  listTeams,
  listWebhooks,
  listWorkflows,
  listWorkflowStepTypes,
} from '@/api/endpoints'
import { useHasPermission } from '@/hooks/useHasPermission'
import { queryKeys } from '@/lib/queryKeys'

import type { FieldSource } from './schemaFields'

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

/** The workflows of an org. Disabled when the user may not read them. */
export function useWorkflowList(orgSlug: string | undefined) {
  const canRead = useHasPermission('workflow:read')
  return useQuery({
    enabled: !!orgSlug && canRead,
    queryFn: ({ signal }) => listWorkflows(orgSlug!, signal),
    queryKey: queryKeys.workflows(orgSlug ?? ''),
  })
}
