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
import { IntegrationsCard } from '@/components/IntegrationsCard'
import { ProjectPluginsSection } from '@/components/project/ProjectPluginsSection'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import { Checkbox } from '@/components/ui/checkbox'
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
  const canRescore =
    isAdmin || (user?.permissions ?? []).includes('scoring_policy:rescore')
  const canResyncDeployments =
    isAdmin || (user?.permissions ?? []).includes('project:deployment:write')
  const { patch, scheduleScoreRefresh } = useProjectPatch(orgSlug, project.id)
  const [deleteConfirmSlug, setDeleteConfirmSlug] = useState('')
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)
  const [deleteRepository, setDeleteRepository] = useState(true)
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
    mutationFn: () => deleteProject(orgSlug, project.id, { deleteRepository }),
    onError: mutationErrorHandler('delete project'),
    onSuccess: (data) => {
      // Delete commits before the lifecycle dispatch runs, so a plugin
      // failure (e.g. the GitHub repo delete) does not roll back the
      // project removal -- surface it instead of swallowing.
      const failed = (data?.lifecycle_results ?? []).filter(
        (result) => result.status === 'failed',
      )
      if (failed.length > 0) {
        toast.warning(
          `Project deleted, but ${failed.length} integration${
            failed.length > 1 ? 's' : ''
          } failed`,
          {
            description: (
              <ul className="mt-1 space-y-0.5">
                {failed.map((result) => (
                  <li key={result.plugin_id}>
                    <span className="font-medium">{result.plugin_slug}</span>:{' '}
                    {result.message ?? 'unknown error'}
                  </li>
                ))}
              </ul>
            ),
            duration: 10000,
          },
        )
      }
      navigate('/')
    },
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
    onSuccess: (data, action) => {
      const base =
        action === 'unarchive' ? 'Project restored' : 'Project archived'
      // The Imbi state change always succeeds here; per-plugin lifecycle
      // handlers (e.g. archiving the GitHub repo) can still fail without
      // rolling it back. Surface those failures so they are not silent.
      const failed = (data.lifecycle_results ?? []).filter(
        (result) => result.status === 'failed',
      )
      if (failed.length > 0) {
        toast.error(
          `${base}, but ${failed.length} integration${
            failed.length > 1 ? 's' : ''
          } failed`,
          {
            description: (
              <ul className="mt-1 space-y-0.5">
                {failed.map((result) => (
                  <li key={result.plugin_id}>
                    <span className="font-medium">{result.plugin_slug}</span>:{' '}
                    {result.message ?? 'unknown error'}
                  </li>
                ))}
              </ul>
            ),
            duration: 10000,
          },
        )
      } else {
        toast.success(base)
      }
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

  // Whether any lifecycle plugin is assigned to the project (project-
  // level or via project type).  Drives the "Also delete the associated
  // repository" checkbox in the delete-project flow: when no lifecycle
  // plugin is present the checkbox is suppressed because there is no
  // remote to delete.
  const hasLifecyclePlugin = useMemo(
    () => projectPlugins.some((assignment) => assignment.tab === 'lifecycle'),
    [projectPlugins],
  )

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

      <IntegrationsCard orgSlug={orgSlug} projectId={project.id} />

      <ProjectPluginsSection orgSlug={orgSlug} projectId={project.id} />

      {(canRescore || (canResyncDeployments && deploymentPlugin)) && (
        <Card>
          <CardHeader>
            <CardTitle>Utility Functions</CardTitle>
          </CardHeader>
          <CardContent className="flex gap-2">
            {canRescore && (
              <Button
                disabled={rescoreMutation.isPending}
                onClick={() => rescoreMutation.mutate()}
                size="sm"
                variant="outline"
              >
                {rescoreMutation.isPending ? 'Enqueuing...' : 'Recompute Score'}
              </Button>
            )}
            {canResyncDeployments && deploymentPlugin && (
              <Button
                disabled={resyncMutation.isPending}
                onClick={() => resyncMutation.mutate()}
                size="sm"
                variant="outline"
              >
                {resyncMutation.isPending ? 'Syncing...' : 'Sync Deployments'}
              </Button>
            )}
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
              disabled={!project.id}
              onClick={() => setShowDeleteConfirm(true)}
              size="sm"
              variant="destructive"
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
              {hasLifecyclePlugin ? (
                <label className="text-secondary flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={deleteRepository}
                    disabled={deleteMutation.isPending}
                    onCheckedChange={(checked) =>
                      setDeleteRepository(checked === true)
                    }
                  />
                  <span>
                    Also delete the associated repository -- uncheck to keep the
                    remote in place after retiring the project.
                  </span>
                </label>
              ) : null}
              <div className="flex gap-2">
                <Button
                  disabled={
                    deleteConfirmSlug !== project.slug ||
                    deleteMutation.isPending
                  }
                  onClick={() => deleteMutation.mutate()}
                  size="sm"
                  variant="destructive"
                >
                  {deleteMutation.isPending ? 'Deleting...' : 'Confirm Delete'}
                </Button>
                <Button
                  disabled={deleteMutation.isPending}
                  onClick={() => {
                    setShowDeleteConfirm(false)
                    setDeleteConfirmSlug('')
                    setDeleteRepository(true)
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
