import { useState, useMemo } from 'react'
import { Globe } from 'lucide-react'
import { formatRelativeDate } from '@/lib/formatDate'
import { EntityIcon } from '@/components/ui/entity-icon'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { LabelChip } from '@/components/ui/label-chip'
import { AdminSection } from './AdminSection'
import { EnvironmentForm } from './environments/EnvironmentForm'
import { EnvironmentDetail } from './environments/EnvironmentDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import {
  listEnvironments,
  deleteEnvironment,
  createEnvironment,
  updateEnvironment,
} from '@/api/endpoints'
import { buildDiffPatch } from '@/lib/json-patch'
import type { Environment, EnvironmentCreate, PatchOperation } from '@/types'

export function EnvironmentManagement() {
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
    items: environments,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    Environment,
    { orgSlug: string; env: EnvironmentCreate },
    { orgSlug: string; slug: string; operations: PatchOperation[] },
    { orgSlug: string; slug: string }
  >({
    queryKey: ['environments', orgSlug],
    listFn: orgSlug ? (signal) => listEnvironments(orgSlug, signal) : null,
    createFn: ({ orgSlug, env }) => createEnvironment(orgSlug, env),
    updateFn: ({ orgSlug, slug, operations }) =>
      updateEnvironment(orgSlug, slug, operations),
    deleteFn: ({ orgSlug, slug }) => deleteEnvironment(orgSlug, slug),
    onMutationSuccess: goToList,
    deleteErrorLabel: 'environment',
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
    } else if (selectedEnvSlug && selectedEnvironment) {
      const operations = buildDiffPatch(
        selectedEnvironment as unknown as Record<string, unknown>,
        envData as unknown as Record<string, unknown>,
        { fields: Object.keys(envData) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({
        orgSlug: selectedEnvironment.organization.slug || formOrgSlug,
        slug: selectedEnvSlug,
        operations,
      })
    }
  }

  const handleCancel = () => {
    goToList()
  }

  if (!orgSlug && !isLoading && !error) {
    return (
      <div className="py-12 text-center text-tertiary">
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
    <AdminSection
      searchPlaceholder="Search environments..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Environment"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading environments..."
      error={error}
      errorTitle="Failed to load environments"
    >
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
                    <Globe className="h-4 w-4 text-success" />
                  )}
                </div>
                <div>
                  <div className="text-primary">{env.name}</div>
                  {env.description && (
                    <div className="text-sm text-tertiary">
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
              <span className="text-secondary">{env.sort_order ?? 0}</span>
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
    </AdminSection>
  )
}
