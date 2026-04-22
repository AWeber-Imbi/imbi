import { useState, useMemo } from 'react'
import { Cloud } from 'lucide-react'
import { EntityIcon } from '@/components/ui/entity-icon'
import { Card, CardContent, CardDescription } from '@/components/ui/card'
import { AdminTable, type AdminTableColumn } from '@/components/ui/admin-table'
import { AdminSection } from './AdminSection'
import { ThirdPartyServiceForm } from './third-party-services/ThirdPartyServiceForm'
import { ThirdPartyServiceDetail } from './third-party-services/ThirdPartyServiceDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import {
  listThirdPartyServices,
  deleteThirdPartyService,
  createThirdPartyService,
  updateThirdPartyService,
} from '@/api/endpoints'
import { statusBadgeVariant } from '@/lib/status-colors'
import { Badge } from '@/components/ui/badge'
import type { ThirdPartyService, ThirdPartyServiceCreate } from '@/types'

export function ThirdPartyServiceManagement() {
  const { selectedOrganization } = useOrganization()
  const {
    viewMode,
    slug: selectedSlug,
    goToList,
    goToCreate,
    goToDetail,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')

  const orgSlug = selectedOrganization?.slug

  const {
    items: services,
    isLoading,
    error,
    createMutation,
    updateMutation,
    deleteMutation,
  } = useAdminCrud<
    ThirdPartyService,
    ThirdPartyServiceCreate,
    { slug: string; svc: ThirdPartyServiceCreate },
    string
  >({
    queryKey: ['third-party-services', orgSlug],
    listFn: orgSlug ? () => listThirdPartyServices(orgSlug) : null,
    createFn: (svc) => {
      if (!orgSlug) throw new Error('No organization selected')
      return createThirdPartyService(orgSlug, svc)
    },
    updateFn: ({ slug, svc }) => {
      if (!orgSlug) throw new Error('No organization selected')
      return updateThirdPartyService(orgSlug, slug, svc)
    },
    deleteFn: (slug) => {
      if (!orgSlug) throw new Error('No organization selected')
      return deleteThirdPartyService(orgSlug, slug)
    },
    onMutationSuccess: goToList,
    deleteErrorLabel: 'service',
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
    } else if (selectedSlug) {
      updateMutation.mutate({ slug: selectedSlug, svc: svcData })
    }
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ThirdPartyServiceForm
        service={selectedService}
        onSave={handleSave}
        onCancel={goToList}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedService) {
    return (
      <ThirdPartyServiceDetail
        service={selectedService}
        onEdit={() => goToEdit(selectedService.slug)}
        onBack={goToList}
      />
    )
  }

  const columns: AdminTableColumn<ThirdPartyService>[] = [
    {
      key: 'service',
      header: 'Service',
      headerAlign: 'left',
      cellAlign: 'left',
      render: (svc) => (
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg bg-purple-50 dark:bg-purple-900/30">
            {svc.icon ? (
              <EntityIcon
                icon={svc.icon}
                className="h-5 w-5 rounded object-cover"
              />
            ) : (
              <Cloud className="h-4 w-4 text-purple-600 dark:text-purple-400" />
            )}
          </div>
          <div>
            <div className="text-primary">{svc.name}</div>
            {svc.description && (
              <div className="max-w-xs truncate text-sm text-tertiary">
                {svc.description}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      key: 'vendor',
      header: 'Vendor',
      headerAlign: 'left',
      cellAlign: 'left',
      render: (svc) => (
        <span className="text-sm text-muted-foreground">{svc.vendor}</span>
      ),
    },
    {
      key: 'category',
      header: 'Category',
      headerAlign: 'left',
      cellAlign: 'left',
      render: (svc) =>
        svc.category ?? <span className="text-muted-foreground">--</span>,
    },
    {
      key: 'status',
      header: 'Status',
      headerAlign: 'center',
      cellAlign: 'center',
      render: (svc) => (
        <Badge variant={statusBadgeVariant(svc.status)}>{svc.status}</Badge>
      ),
    },
    {
      key: 'team',
      header: 'Team',
      headerAlign: 'left',
      cellAlign: 'left',
      render: (svc) =>
        svc.team?.name ?? <span className="text-muted-foreground">--</span>,
    },
  ]

  return (
    <AdminSection
      searchPlaceholder="Search services..."
      search={searchQuery}
      onSearchChange={setSearchQuery}
      createLabel="New Service"
      onCreate={goToCreate}
      isLoading={isLoading}
      loadingLabel="Loading third-party services..."
      error={error}
      errorTitle="Failed to load third-party services"
    >
      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Total Services
            </CardDescription>
            <div className="mt-1 text-2xl text-primary">
              {filteredServices.length}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">Active</CardDescription>
            <div className="mt-1 text-2xl text-success">
              {statusCounts.active}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Evaluating
            </CardDescription>
            <div className="mt-1 text-2xl text-info">
              {statusCounts.evaluating}
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4">
            <CardDescription className="text-secondary">
              Deprecated
            </CardDescription>
            <div className="mt-1 text-2xl text-warning">
              {statusCounts.deprecated}
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Services Table */}
      <AdminTable<ThirdPartyService>
        columns={columns}
        rows={filteredServices}
        getRowKey={(svc) => svc.slug}
        getDeleteLabel={(svc) => svc.name}
        onRowClick={(svc) => goToDetail(svc.slug)}
        onDelete={(svc) => deleteMutation.mutate(svc.slug)}
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery
            ? 'No services found matching your search.'
            : selectedOrganization
              ? `No third-party services in ${selectedOrganization.name} yet.`
              : 'No third-party services created yet.'
        }
      />
    </AdminSection>
  )
}
