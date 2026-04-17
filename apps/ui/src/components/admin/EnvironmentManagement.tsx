import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { ApiError } from '@/api/client'
import { Plus, Search, Globe, AlertCircle } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { EntityIcon } from '@/components/ui/entity-icon'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { LabelChip } from '@/components/ui/label-chip'
import { EnvironmentForm } from './environments/EnvironmentForm'
import { EnvironmentDetail } from './environments/EnvironmentDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listEnvironments,
  deleteEnvironment,
  createEnvironment,
  updateEnvironment,
} from '@/api/endpoints'
import type { EnvironmentCreate } from '@/types'

export function EnvironmentManagement() {
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const {
    viewMode,
    slug: selectedEnvSlug,
    goToList,
    goToCreate,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    data: environments = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['environments', orgSlug],
    queryFn: () => listEnvironments(orgSlug!),
    enabled: !!orgSlug,
  })

  const createMutation = useMutation({
    mutationFn: ({
      orgSlug,
      env,
    }: {
      orgSlug: string
      env: EnvironmentCreate
    }) => createEnvironment(orgSlug, env),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environments', orgSlug] })
      goToList()
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      orgSlug,
      slug,
      env,
    }: {
      orgSlug: string
      slug: string
      env: EnvironmentCreate
    }) => updateEnvironment(orgSlug, slug, env),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environments', orgSlug] })
      goToList()
    },
  })

  const deleteMutation = useMutation({
    mutationFn: ({ orgSlug, slug }: { orgSlug: string; slug: string }) =>
      deleteEnvironment(orgSlug, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['environments', orgSlug] })
    },
    onError: (error: ApiError<{ detail?: string }>) => {
      alert(
        `Failed to delete environment: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  const filteredEnvironments = environments.filter((env) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        env.name.toLowerCase().includes(query) ||
        env.slug.toLowerCase().includes(query) ||
        (env.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedEnvironment = useMemo(
    () => environments.find((e) => e.slug === selectedEnvSlug) || null,
    [environments, selectedEnvSlug],
  )

  type Environment = (typeof environments)[number]

  const handleDelete = (env: Environment) => {
    deleteMutation.mutate({ orgSlug: env.organization.slug, slug: env.slug })
  }

  const canDeleteEnvironment = (env: Environment): CanDeleteResult => {
    const projects = env.relationships?.projects?.count ?? 0
    if (projects === 0) return { allowed: true }
    return {
      allowed: false,
      blockedBy: [{ count: projects, label: 'project', href: '/projects' }],
    }
  }

  const handleSave = (formOrgSlug: string, envData: EnvironmentCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ orgSlug: formOrgSlug, env: envData })
    } else if (selectedEnvSlug) {
      updateMutation.mutate({
        orgSlug: selectedEnvironment?.organization.slug || formOrgSlug,
        slug: selectedEnvSlug,
        env: envData,
      })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={'text-sm text-secondary'}>Loading environments...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${'border-danger bg-danger text-danger'}`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load environments</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  if (!orgSlug) {
    return (
      <div className={'py-12 text-center text-tertiary'}>
        Select an organization to manage environments.
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <EnvironmentForm
        environment={selectedEnvironment}
        onSave={handleSave}
        onCancel={handleCancel}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedEnvironment) {
    return (
      <EnvironmentDetail
        environment={selectedEnvironment}
        onEdit={() => goToEdit(selectedEnvironment.slug)}
        onBack={handleCancel}
      />
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex-1">
          <div className="relative max-w-md">
            <Search
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${'text-tertiary'}`}
            />
            <Input
              placeholder="Search environments..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={'pl-10'}
            />
          </div>
        </div>
        <Button
          onClick={goToCreate}
          className="bg-action text-action-foreground hover:bg-action-hover"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Environment
        </Button>
      </div>

      <AdminTable
        columns={[
          {
            key: 'name',
            header: 'Environment',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (env) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-success'
                  }
                >
                  {env.icon ? (
                    <EntityIcon
                      icon={env.icon}
                      className="size-5 rounded object-cover"
                    />
                  ) : (
                    <Globe className={'h-4 w-4 text-success'} />
                  )}
                </div>
                <div>
                  <div className={'text-primary'}>{env.name}</div>
                  {env.description && (
                    <div className={'text-sm text-tertiary'}>
                      {env.description}
                    </div>
                  )}
                </div>
              </div>
            ),
          },
          {
            key: 'slug',
            header: 'Slug',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (env) =>
              env.label_color ? (
                <LabelChip hex={env.label_color} className="font-mono">
                  {env.slug}
                </LabelChip>
              ) : (
                <code
                  className={
                    'whitespace-nowrap rounded bg-secondary px-2 py-1 text-primary'
                  }
                >
                  {env.slug}
                </code>
              ),
          },
          {
            key: 'order',
            header: 'Order',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (env) => (
              <span className={'text-secondary'}>{env.sort_order ?? 0}</span>
            ),
          },
          {
            key: 'projects',
            header: 'Projects',
            headerAlign: 'right',
            cellAlign: 'right',
            render: (env) => (
              <span
                className={
                  (env.relationships?.projects?.count ?? 0) === 0
                    ? 'text-tertiary'
                    : 'text-secondary'
                }
              >
                {env.relationships?.projects?.count ?? 0}
              </span>
            ),
          },
          {
            key: 'updated',
            header: 'Last Updated',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (env) =>
              formatRelativeDate(env.updated_at ?? env.created_at),
          },
        ]}
        rows={filteredEnvironments}
        getRowKey={(env) => env.slug}
        getDeleteLabel={(env) => env.name}
        onRowClick={(env) => goToEdit(env.slug)}
        onDelete={handleDelete}
        canDelete={canDeleteEnvironment}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery
            ? 'No environments found matching your search.'
            : selectedOrganization
              ? `No environments in ${selectedOrganization.name} yet.`
              : 'No environments created yet.'
        }
      />
    </div>
  )
}
