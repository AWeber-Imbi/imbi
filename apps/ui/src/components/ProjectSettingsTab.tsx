import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { extractApiErrorDetail } from '@/lib/apiError'
import { sortEnvironments } from '@/lib/utils'
import {
  listLinkDefinitions,
  listEnvironments,
  patchProject,
  deleteProject,
} from '@/api/endpoints'
import { EditIdentifiersCard } from '@/components/EditIdentifiersCard'
import { EditLinksCard } from '@/components/EditLinksCard'
import { EditEnvironmentsCard } from '@/components/EditEnvironmentsCard'
import type { Project } from '@/types'
import { useProjectPatch } from '@/hooks/useProjectPatch'

export function ProjectSettingsTab({ project }: { project: Project }) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()
  const navigate = useNavigate()
  const { patch } = useProjectPatch(orgSlug, project.id)
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
    onSuccess: () => navigate('/'),
    onError: mutationErrorHandler('delete project'),
  })

  const {
    data: linkDefs = [],
    isLoading: linkDefsLoading,
    isError: linkDefsError,
  } = useQuery({
    queryKey: ['linkDefinitions', orgSlug],
    queryFn: ({ signal }) => listLinkDefinitions(orgSlug, signal),
    enabled: !!orgSlug,
  })

  const sortedEnvironments = useMemo(
    () => sortEnvironments(project.environments || []),
    [project.environments],
  )

  const { data: availableEnvironments = [] } = useQuery({
    queryKey: ['environments', orgSlug],
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    enabled: !!orgSlug,
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
        environments={sortedEnvironments}
        availableEnvironments={availableEnvironments}
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
          <Button variant="outline" size="sm" disabled>
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
            facts, operation logs, and notes. Are you absolutely sure?
          </CardDescription>
        </CardHeader>
        <CardContent>
          {!showDeleteConfirm ? (
            <Button
              variant="outline"
              size="sm"
              className="border-danger bg-red-700 text-white hover:bg-red-800"
              onClick={() => setShowDeleteConfirm(true)}
              disabled={!project.id}
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
                value={deleteConfirmSlug}
                onChange={(e) => setDeleteConfirmSlug(e.target.value)}
                placeholder={project.slug}
                disabled={deleteMutation.isPending}
                className=""
              />
              <div className="flex gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className={
                    'border-danger bg-red-700 text-white hover:bg-red-800'
                  }
                  onClick={() => deleteMutation.mutate()}
                  disabled={
                    deleteConfirmSlug !== project.slug ||
                    deleteMutation.isPending
                  }
                >
                  {deleteMutation.isPending ? 'Deleting...' : 'Confirm Delete'}
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setShowDeleteConfirm(false)
                    setDeleteConfirmSlug('')
                  }}
                  disabled={deleteMutation.isPending}
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
