import { useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  archiveProject,
  deleteProject,
  listEnvironments,
  listLinkDefinitions,
  listProjectPlugins,
  patchProject,
  rescoreProject,
  unarchiveProject,
} from '@/api/endpoints'
import { EditEnvironmentsCard } from '@/components/EditEnvironmentsCard'
import { EditIdentifiersCard } from '@/components/EditIdentifiersCard'
import { EditLinksCard } from '@/components/EditLinksCard'
import { ProjectPluginsSection } from '@/components/project/ProjectPluginsSection'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
import { useProjectDeploymentResync } from '@/hooks/useDeploymentResync'
import { useProjectPatch } from '@/hooks/useProjectPatch'
import { extractApiErrorDetail } from '@/lib/apiError'
import { sortEnvironments } from '@/lib/utils'
import type { Project } from '@/types'

export function ProjectSettingsTab({ project }: { project: Project }) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { user } = useAuth()
  const isAdmin = user?.is_admin === true
  const { patch, scheduleScoreRefresh } = useProjectPatch(orgSlug, project.id)
  const [deleteConfirmSlug, setDeleteConfirmSlug] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [showArchiveConfirm, setShowArchiveConfirm] = useState(false)
  const isArchived = project.archived === true

  const invalidateProject = () => {
    queryClient.invalidateQueries({
      queryKey: ['project', orgSlug, project.id],
    })
  }

  const mutationErrorHandler = (label: string) => (error: unknown) => {
    toast.error(`Failed to ${label}: ${extractApiErrorDetail(error)}`)
  }

  const deleteMutation = useMutation({
    mutationFn: () => deleteProject(orgSlug, project.id),
    onError: mutationErrorHandler('delete project'),
    onSuccess: () => navigate('/'),
  })

  const archiveMutation = useMutation({
    mutationFn: (action: 'archive' | 'unarchive') =>
      action === 'unarchive'
        ? unarchiveProject(orgSlug, project.id)
        : archiveProject(orgSlug, project.id),
    onError: (error, action) =>
      mutationErrorHandler(
        action === 'unarchive' ? 'unarchive project' : 'archive project',
      )(error),
    onSuccess: (_data, action) => {
      toast.success(
        action === 'unarchive' ? 'Project restored' : 'Project archived',
      )
      setShowArchiveConfirm(false)
      invalidateProject()
      queryClient.invalidateQueries({ queryKey: ['projects', orgSlug] })
    },
  })

  const rescoreMutation = useMutation({
    mutationFn: () => rescoreProject(project.id),
    onError: mutationErrorHandler('recompute score'),
    onSuccess: () => {
      toast.success('Score recompute enqueued')
      scheduleScoreRefresh()
    },
  })

  const { data: projectPlugins = [] } = useQuery({
    enabled: !!orgSlug && !!project.id,
    queryFn: ({ signal }) => listProjectPlugins(orgSlug, project.id, signal),
    queryKey: ['projectPlugins', orgSlug, project.id],
  })

  // Pick the project's deployment plugin (project-level or inherited)
  // and only render the resync card when its manifest opts in. Multiple
  // deployment assignments are rare; we resync the default one and
  // expose ``source`` via the existing endpoint flag if needed later.
  const deploymentPlugin = useMemo(() => {
    const candidates = projectPlugins.filter(
      (assignment) =>
        assignment.tab === 'deployment' &&
        assignment.supports_deployment_sync === true,
    )
    return candidates.find((assignment) => assignment.default) ?? candidates[0]
  }, [projectPlugins])

  const resyncMutation = useProjectDeploymentResync(orgSlug, project.id)

  const {
    data: linkDefs = [],
    isError: linkDefsError,
    isLoading: linkDefsLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listLinkDefinitions(orgSlug, signal),
    queryKey: ['linkDefinitions', orgSlug],
  })

  const sortedEnvironments = useMemo(
    () => sortEnvironments(project.environments || []),
    [project.environments],
  )

  const { data: availableEnvironments = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: ['environments', orgSlug],
  })

  return (
    <div className="space-y-6">
      {linkDefsLoading && (
        <Card>
          <CardContent>
            <p className="text-tertiary text-sm">Loading link definitions...</p>
          </CardContent>
        </Card>
      )}
      {linkDefsError && (
        <Card>
          <CardContent>
            <p className="text-sm text-red-600 dark:text-red-400">
              Failed to load link definitions.
            </p>
          </CardContent>
        </Card>
      )}
      {!linkDefsLoading && !linkDefsError && linkDefs.length > 0 && (
        <EditLinksCard
          linkDefs={linkDefs}
          links={project.links || {}}
          onPatch={(entries) => patch('/links', entries)}
        />
      )}

      <EditEnvironmentsCard
        availableEnvironments={availableEnvironments}
        environments={sortedEnvironments}
        onPatch={async (envData) => {
          try {
            await patchProject(orgSlug, project.id, [
              { op: 'replace', path: '/environments', value: envData },
            ])
          } catch (error) {
            toast.error(`Save failed: ${extractApiErrorDetail(error)}`)
            throw error
          }
          invalidateProject()
        }}
      />

      <EditIdentifiersCard
        identifiers={project.identifiers || {}}
        onPatch={(entries) => patch('/identifiers', entries)}
      />

      <ProjectPluginsSection orgSlug={orgSlug} projectId={project.id} />

      {deploymentPlugin && (
        <Card>
          <CardHeader>
            <CardTitle>Resync deployments</CardTitle>
            <CardDescription className="text-secondary">
              Fetch the latest deployment for each environment from{' '}
              <strong>{deploymentPlugin.label}</strong> and backfill releases
              and deployment history. Useful when webhook delivery has lapsed or
              the badge appears stale.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              disabled={resyncMutation.isPending}
              onClick={() => resyncMutation.mutate()}
              size="sm"
              variant="outline"
            >
              {resyncMutation.isPending ? 'Resyncing...' : 'Resync Deployments'}
            </Button>
          </CardContent>
        </Card>
      )}

      {isAdmin && (
        <Card>
          <CardHeader>
            <CardTitle>Recompute score</CardTitle>
            <CardDescription className="text-secondary">
              Enqueue an immediate score recompute for this project. Use this
              after manually correcting project data or when the displayed score
              appears stale.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              disabled={rescoreMutation.isPending}
              onClick={() => rescoreMutation.mutate()}
              size="sm"
              variant="outline"
            >
              {rescoreMutation.isPending ? 'Enqueuing...' : 'Recompute Score'}
            </Button>
          </CardContent>
        </Card>
      )}

      <Card className="border-amber-300">
        <CardHeader>
          <CardTitle>
            {isArchived ? 'Restore project' : 'Archive project'}
          </CardTitle>
          <CardDescription className="text-secondary">
            {isArchived
              ? 'This project is archived. Restoring will return it to the dashboard and search results.'
              : 'Archiving the project will hide it from the dashboard and search results. Existing data is preserved and the project can be restored at any time.'}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button
            disabled={archiveMutation.isPending}
            onClick={() => {
              if (isArchived) {
                archiveMutation.mutate('unarchive')
              } else {
                setShowArchiveConfirm(true)
              }
            }}
            size="sm"
            variant="outline"
          >
            {archiveMutation.isPending
              ? isArchived
                ? 'Restoring...'
                : 'Archiving...'
              : isArchived
                ? 'Restore project'
                : 'Archive project'}
          </Button>
        </CardContent>
      </Card>

      <ConfirmDialog
        confirmLabel="Archive project"
        description={`Archiving ${project.slug} will hide it from the dashboard and search results until it is restored.`}
        onCancel={() => setShowArchiveConfirm(false)}
        onConfirm={() => archiveMutation.mutate('archive')}
        open={showArchiveConfirm}
        title="Archive this project?"
      />

      <Card className="border-red-300">
        <CardHeader>
          <CardTitle>Delete project</CardTitle>
          <CardDescription className="text-secondary">
            This action will <strong>permanently delete</strong>{' '}
            <code
              className={
                'bg-secondary text-primary rounded px-1.5 py-0.5 font-mono text-sm'
              }
            >
              {project.slug}
            </code>{' '}
            immediately, removing the project and all associated data, including
            facts, operation logs, and documents. Are you absolutely sure?
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!showDeleteConfirm ? (
            <Button
              className="border-danger bg-red-700 text-white hover:bg-red-800"
              disabled={!project.id}
              onClick={() => setShowDeleteConfirm(true)}
              size="sm"
              variant="outline"
            >
              Delete Project
            </Button>
          ) : (
            <div className="space-y-3">
              <p className="text-secondary text-sm">
                Type{' '}
                <code
                  className={
                    'bg-secondary text-primary rounded px-1.5 py-0.5 font-mono text-sm'
                  }
                >
                  {project.slug}
                </code>{' '}
                to confirm deletion:
              </p>
              <Input
                className=""
                disabled={deleteMutation.isPending}
                onChange={(e) => setDeleteConfirmSlug(e.target.value)}
                placeholder={project.slug}
                value={deleteConfirmSlug}
              />
              <div className="flex gap-2">
                <Button
                  className={
                    'border-danger bg-red-700 text-white hover:bg-red-800'
                  }
                  disabled={
                    deleteConfirmSlug !== project.slug ||
                    deleteMutation.isPending
                  }
                  onClick={() => deleteMutation.mutate()}
                  size="sm"
                  variant="outline"
                >
                  {deleteMutation.isPending ? 'Deleting...' : 'Confirm Delete'}
                </Button>
                <Button
                  disabled={deleteMutation.isPending}
                  onClick={() => {
                    setShowDeleteConfirm(false)
                    setDeleteConfirmSlug('')
                  }}
                  size="sm"
                  variant="outline"
                >
                  Cancel
                </Button>
              </div>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
