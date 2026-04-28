import { useMemo, useState } from 'react'

import { Globe } from 'lucide-react'

import {
  createEnvironment,
  deleteEnvironment,
  listEnvironments,
  updateEnvironment,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import type { CanDeleteResult } from '@/components/ui/admin-table'
import { EntityIcon } from '@/components/ui/entity-icon'
import { LabelChip } from '@/components/ui/label-chip'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { formatRelativeDate } from '@/lib/formatDate'
import { buildDiffPatch } from '@/lib/json-patch'
import type { Environment, EnvironmentCreate, PatchOperation } from '@/types'

import { AdminSection } from './AdminSection'
import { EnvironmentDetail } from './environments/EnvironmentDetail'
import { EnvironmentForm } from './environments/EnvironmentForm'

export function EnvironmentManagement() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedEnvSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: environments,
    updateMutation,
  } = useAdminCrud<
    Environment,
    { env: EnvironmentCreate; orgSlug: string },
    { operations: PatchOperation[]; orgSlug: string; slug: string },
    { orgSlug: string; slug: string }
  >({
    createFn: ({ env, orgSlug }) => createEnvironment(orgSlug, env),
    deleteErrorLabel: 'environment',
    deleteFn: ({ orgSlug, slug }) => deleteEnvironment(orgSlug, slug),
    listFn: orgSlug ? (signal) => listEnvironments(orgSlug, signal) : null,
    onMutationSuccess: goToList,
    queryKey: ['environments', orgSlug],
    updateFn: ({ operations, orgSlug, slug }) =>
      updateEnvironment(orgSlug, slug, operations),
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
      blockedBy: [{ count: projects, href: '/projects', label: 'project' }],
    }
  }

  const handleSave = (formOrgSlug: string, envData: EnvironmentCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate({ env: envData, orgSlug: formOrgSlug })
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
        operations,
        orgSlug: selectedEnvironment.organization.slug || formOrgSlug,
        slug: selectedEnvSlug,
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
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={handleCancel}
        onSave={handleSave}
      />
    )
  }

  if (viewMode === 'detail' && selectedEnvironment) {
    return (
      <EnvironmentDetail
        environment={selectedEnvironment}
        onBack={handleCancel}
        onEdit={() => goToEdit(selectedEnvironment.slug)}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Environment"
      error={error}
      errorTitle="Failed to load environments"
      isLoading={isLoading}
      loadingLabel="Loading environments..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search environments..."
    >
      <AdminTable
        canDelete={canDeleteEnvironment}
        columns={[
          {
            cellAlign: 'left',
            header: 'Environment',
            headerAlign: 'left',
            key: 'name',
            render: (env) => (
              <div className="flex items-center gap-3">
                <div
                  className={
                    'flex size-8 flex-shrink-0 items-center justify-center rounded-lg bg-success'
                  }
                >
                  {env.icon ? (
                    <EntityIcon
                      className="size-5 rounded object-cover"
                      icon={env.icon}
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
            cellAlign: 'center',
            header: 'Slug',
            headerAlign: 'center',
            key: 'slug',
            render: (env) =>
              env.label_color ? (
                <LabelChip className="font-mono" hex={env.label_color}>
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
            cellAlign: 'center',
            header: 'Order',
            headerAlign: 'center',
            key: 'order',
            render: (env) => (
              <span className="text-secondary">{env.sort_order ?? 0}</span>
            ),
          },
          {
            cellAlign: 'right',
            header: 'Projects',
            headerAlign: 'right',
            key: 'projects',
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
            cellAlign: 'center',
            header: 'Last Updated',
            headerAlign: 'center',
            key: 'updated',
            render: (env) =>
              formatRelativeDate(env.updated_at ?? env.created_at),
          },
        ]}
        emptyMessage={
          searchQuery
            ? 'No environments found matching your search.'
            : selectedOrganization
              ? `No environments in ${selectedOrganization.name} yet.`
              : 'No environments created yet.'
        }
        getDeleteLabel={(env) => env.name}
        getRowKey={(env) => env.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={handleDelete}
        onRowClick={(env) => goToEdit(env.slug)}
        rows={filteredEnvironments}
      />
    </AdminSection>
  )
}
