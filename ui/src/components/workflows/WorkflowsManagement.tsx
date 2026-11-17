import { type ReactNode, useMemo } from 'react'

import { Link, useParams, useSearchParams } from 'react-router-dom'

import { agentsPath } from '@/components/agents/agentsNav'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { cn } from '@/lib/utils'

import { RunDetail } from './RunDetail'
import { workflowFailures } from './runs'
import { RunsTab } from './RunsTab'
import { StaleSideEffects } from './StaleSideEffects'
import { WorkflowEditor } from './WorkflowEditor'
import { WorkflowList } from './WorkflowList'
import {
  useOrgRuns,
  useStepTypes,
  useWorkflow,
  useWorkflowList,
} from './workflowQueries'

/**
 * Agents > Workflows. The URL picks the view: `/agents/workflows`
 * (definitions), `/agents/workflows?view=runs` (runs of every
 * workflow), `/agents/workflows/new` (create),
 * `/agents/workflows/<slug>` (editor), and
 * `/agents/workflows/<slug>/runs/<run id>` (one run).
 */
export function WorkflowsManagement() {
  const { action, slug, tab } = useParams<{
    action?: string
    slug?: string
    tab?: string
  }>()
  const [search] = useSearchParams()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canRead = useHasPermission('workflow:read', orgSlug)
  const canCreate = useHasPermission('workflow:create', orgSlug)
  const list = useWorkflowList(orgSlug)
  const stepTypes = useStepTypes(orgSlug)
  const recent = useOrgRuns(orgSlug, 7)
  const failures = useMemo(
    () => workflowFailures(recent.data ?? []),
    [recent.data],
  )

  if (!orgSlug) {
    return (
      <div className="text-tertiary p-8 text-center">
        Select an organization to manage workflows.
      </div>
    )
  }
  if (!canRead) {
    return (
      <div className="text-tertiary p-8 text-center">
        You need the workflow:read permission to see workflows.
      </div>
    )
  }

  if (slug && action === 'runs' && tab) {
    return <RunDetail orgSlug={orgSlug} runId={tab} slug={slug} />
  }
  if (slug && (slug !== 'new' || canCreate)) {
    return (
      <EditorPage
        key={slug}
        orgSlug={orgSlug}
        slug={slug}
        stepTypes={stepTypes}
      />
    )
  }

  const runsView = search.get('view') === 'runs'
  return (
    <div className="flex flex-col gap-6 p-8">
      <StaleSideEffects orgSlug={orgSlug} />
      <div className="flex flex-col gap-3">
        <h1 className="text-h1">Workflows</h1>
        <nav
          aria-label="Workflow views"
          className="border-tertiary flex gap-6 border-b"
        >
          <ViewTab active={!runsView} to={agentsPath('workflows')}>
            Definitions{' '}
            <span className="text-tertiary">{list.data?.length ?? ''}</span>
          </ViewTab>
          <ViewTab
            active={runsView}
            to={`${agentsPath('workflows')}?view=runs`}
          >
            Runs
          </ViewTab>
        </nav>
      </div>
      {runsView ? (
        <RunsTab orgSlug={orgSlug} workflows={list.data ?? []} />
      ) : (
        <WorkflowList
          error={list.error}
          failures={failures}
          loading={list.isLoading}
          stepTypes={stepTypes.data ?? []}
          workflows={list.data ?? []}
        />
      )}
    </div>
  )
}

function EditorPage({
  orgSlug,
  slug,
  stepTypes,
}: {
  orgSlug: string
  slug: string
  stepTypes: ReturnType<typeof useStepTypes>
}) {
  const workflow = useWorkflow(orgSlug, slug)
  const error = stepTypes.error ?? workflow.error
  if (error) {
    return (
      <div className="flex flex-col gap-4 p-8">
        <ErrorBanner error={error} title="Failed to load the workflow" />
        <Link className="text-action text-sm" to={agentsPath('workflows')}>
          Back to workflows
        </Link>
      </div>
    )
  }
  if (!stepTypes.data || (slug !== 'new' && !workflow.data)) {
    return (
      <div className="flex flex-col gap-4 p-8">
        <Sk h={32} r={6} w={240} />
        <Sk h={480} r={12} />
      </div>
    )
  }
  return (
    <WorkflowEditor
      orgSlug={orgSlug}
      stepTypes={stepTypes.data}
      workflow={slug === 'new' ? null : workflow.data!}
    />
  )
}

function ViewTab({
  active,
  children,
  to,
}: {
  active: boolean
  children: ReactNode
  to: string
}) {
  return (
    <Link
      aria-current={active ? 'page' : undefined}
      className={cn(
        '-mb-px border-b-2 px-0.5 pb-2.5 text-sm',
        active
          ? 'border-amber-border font-medium text-primary'
          : 'border-transparent text-secondary hover:text-primary',
      )}
      to={to}
    >
      {children}
    </Link>
  )
}
