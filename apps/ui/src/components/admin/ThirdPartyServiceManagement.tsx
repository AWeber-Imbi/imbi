import { useMemo, useState } from 'react'

import { Cloud } from 'lucide-react'

import {
  createThirdPartyService,
  deleteThirdPartyService,
  listThirdPartyServices,
  updateThirdPartyService,
} from '@/api/endpoints'
import { AdminTable, type AdminTableColumn } from '@/components/ui/admin-table'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import { EntityIcon } from '@/components/ui/entity-icon'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { buildDiffPatch } from '@/lib/json-patch'
import { statusBadgeVariant } from '@/lib/status-colors'
import type {
  PatchOperation,
  ThirdPartyService,
  ThirdPartyServiceCreate,
} from '@/types'

import { AdminSection } from './AdminSection'
import { ThirdPartyServiceDetail } from './third-party-services/ThirdPartyServiceDetail'
import { ThirdPartyServiceForm } from './third-party-services/ThirdPartyServiceForm'

export function ThirdPartyServiceManagement() {
  const { selectedOrganization } = useOrganization()
  const {
    goToCreate,
    goToDetail,
    goToEdit,
    goToList,
    slug: selectedSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const orgSlug = selectedOrganization?.slug

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: services,
    updateMutation,
  } = useAdminCrud<
    ThirdPartyService,
    ThirdPartyServiceCreate,
    { operations: PatchOperation[]; slug: string },
    string
  >({
    createFn: (svc) => {
      if (!orgSlug) throw new Error('No organization selected')
      return createThirdPartyService(orgSlug, svc)
    },
    deleteErrorLabel: 'service',
    deleteFn: (slug) => {
      if (!orgSlug) throw new Error('No organization selected')
      return deleteThirdPartyService(orgSlug, slug)
    },
    listFn: orgSlug
      ? (signal) => listThirdPartyServices(orgSlug, signal)
      : null,
    onMutationSuccess: goToList,
    queryKey: ['third-party-services', orgSlug],
    updateFn: ({ operations, slug }) => {
      if (!orgSlug) throw new Error('No organization selected')
      return updateThirdPartyService(orgSlug, slug, operations)
    },
  })

  const filteredServices = services.filter((svc) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        svc.name.toLowerCase().includes(query) ||
        svc.slug.toLowerCase().includes(query) ||
        svc.vendor.toLowerCase().includes(query) ||
        (svc.category?.toLowerCase().includes(query) ?? false) ||
        (svc.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedService = useMemo(
    () => services.find((s) => s.slug === selectedSlug) || null,
    [services, selectedSlug],
  )

  const statusCounts = useMemo(() => {
    const counts: Record<string, number> = {
      active: 0,
      deprecated: 0,
      evaluating: 0,
      inactive: 0,
    }
    for (const svc of filteredServices) {
      counts[svc.status] = (counts[svc.status] || 0) + 1
    }
    return counts
  }, [filteredServices])

  const handleSave = (svcData: ThirdPartyServiceCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(svcData)
    } else if (selectedSlug && selectedService) {
      const operations = buildDiffPatch(
        selectedService as unknown as Record<string, unknown>,
        svcData as unknown as Record<string, unknown>,
        { fields: Object.keys(svcData) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({ operations, slug: selectedSlug })
    }
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ThirdPartyServiceForm
        error={createMutation.error || updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={goToList}
        onSave={handleSave}
        service={selectedService}
      />
    )
  }

  if (viewMode === 'detail' && selectedService) {
    return (
      <ThirdPartyServiceDetail
        onBack={goToList}
        onEdit={() => goToEdit(selectedService.slug)}
        service={selectedService}
      />
    )
  }

  const columns: AdminTableColumn<ThirdPartyService>[] = [
    {
      cellAlign: 'left',
      header: 'Service',
      headerAlign: 'left',
      key: 'service',
      render: (svc) => (
        <div className="flex items-center gap-3">
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-purple-50 dark:bg-purple-900/30">
            {svc.icon ? (
              <EntityIcon
                className="size-5 rounded object-cover"
                icon={svc.icon}
              />
            ) : (
              <Cloud className="size-4 text-purple-600 dark:text-purple-400" />
            )}
          </div>
          <div>
            <div className="text-primary">{svc.name}</div>
            {svc.description && (
              <div className="text-tertiary max-w-xs truncate text-sm">
                {svc.description}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      cellAlign: 'left',
      header: 'Vendor',
      headerAlign: 'left',
      key: 'vendor',
      render: (svc) => (
        <span className="text-muted-foreground text-sm">{svc.vendor}</span>
      ),
    },
    {
      cellAlign: 'left',
      header: 'Category',
      headerAlign: 'left',
      key: 'category',
      render: (svc) =>
        svc.category ?? <span className="text-muted-foreground">--</span>,
    },
    {
      cellAlign: 'center',
      header: 'Status',
      headerAlign: 'center',
      key: 'status',
      render: (svc) => (
        <Badge variant={statusBadgeVariant(svc.status)}>{svc.status}</Badge>
      ),
    },
    {
      cellAlign: 'left',
      header: 'Team',
      headerAlign: 'left',
      key: 'team',
      render: (svc) =>
        (svc.team?.name as string | undefined) ?? (
          <span className="text-muted-foreground">--</span>
        ),
    },
  ]

  return (
    <AdminSection
      createLabel="New Service"
      error={error}
      errorTitle="Failed to load third-party services"
      isLoading={isLoading}
      loadingLabel="Loading third-party services..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search services..."
    >
      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Total Services
            </CardDescription>
            <div className="text-primary mt-1 text-2xl">
              {filteredServices.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">Active</CardDescription>
            <div className="text-success mt-1 text-2xl">
              {statusCounts.active}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Evaluating
            </CardDescription>
            <div className="text-info mt-1 text-2xl">
              {statusCounts.evaluating}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Deprecated
            </CardDescription>
            <div className="text-warning mt-1 text-2xl">
              {statusCounts.deprecated}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Services Table */}
      <AdminTable<ThirdPartyService>
        columns={columns}
        emptyMessage={
          searchQuery
            ? 'No services found matching your search.'
            : selectedOrganization
              ? `No third-party services in ${selectedOrganization.name} yet.`
              : 'No third-party services created yet.'
        }
        getDeleteLabel={(svc) => svc.name}
        getRowKey={(svc) => svc.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={(svc) => deleteMutation.mutate(svc.slug)}
        onRowClick={(svc) => goToDetail(svc.slug)}
        rows={filteredServices}
      />
    </AdminSection>
  )
}
