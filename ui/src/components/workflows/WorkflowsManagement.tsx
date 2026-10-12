import { Link, useParams } from 'react-router-dom'

import { agentsPath } from '@/components/agents/agentsNav'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'

import { WorkflowEditor } from './WorkflowEditor'
import { WorkflowList } from './WorkflowList'
import { useStepTypes, useWorkflow, useWorkflowList } from './workflowQueries'

/**
 * Agents > Workflows. The URL picks the view: `/agents/workflows`
 * (list), `/agents/workflows/new` (create), and
 * `/agents/workflows/<slug>` (editor).
 */
export function WorkflowsManagement() {
  const { slug } = useParams<{ slug?: string }>()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const canRead = useHasPermission('workflow:read')
  const canCreate = useHasPermission('workflow:create')
  const list = useWorkflowList(orgSlug)
  const stepTypes = useStepTypes(orgSlug)

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

  return (
    <div className="p-8">
      <WorkflowList
        error={list.error}
        loading={list.isLoading}
        stepTypes={stepTypes.data ?? []}
        workflows={list.data ?? []}
      />
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
