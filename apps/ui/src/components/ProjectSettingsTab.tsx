import { useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'

import {
  deleteProject,
  listEnvironments,
  listLinkDefinitions,
  patchProject,
  rescoreProject,
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
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAuth } from '@/hooks/useAuth'
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

  const rescoreMutation = useMutation({
    mutationFn: () => rescoreProject(project.id),
    onError: mutationErrorHandler('recompute score'),
    onSuccess: () => {
      toast.success('Score recompute enqueued')
      scheduleScoreRefresh()
    },
  })

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
            <p className="text-sm text-tertiary">Loading link definitions...</p>
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
          <CardTitle>Archive project</CardTitle>
          <CardDescription className="text-secondary">
            Archiving the project will make it entirely read only. It will be
            hidden from the dashboard, won&apos;t show up in searches, and will
            be disabled as a dependency for any other projects that are
            dependent upon it.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Button disabled size="sm" variant="outline">
            Archive project
          </Button>
        </CardContent>
      </Card>

      <Card className="border-red-300">
        <CardHeader>
          <CardTitle>Delete project</CardTitle>
          <CardDescription className="text-secondary">
            This action will <strong>permanently delete</strong>{' '}
            <code
              className={
                'rounded bg-secondary px-1.5 py-0.5 font-mono text-sm text-primary'
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
              <p className="text-sm text-secondary">
                Type{' '}
                <code
                  className={
                    'rounded bg-secondary px-1.5 py-0.5 font-mono text-sm text-primary'
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
