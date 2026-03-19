import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import type { AxiosError } from 'axios'
import { Plus, Search, Trash2, Cloud, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ThirdPartyServiceForm } from './third-party-services/ThirdPartyServiceForm'
import { ThirdPartyServiceDetail } from './third-party-services/ThirdPartyServiceDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import {
  listThirdPartyServices,
  deleteThirdPartyService,
  createThirdPartyService,
  updateThirdPartyService,
} from '@/api/endpoints'
import type { ThirdPartyServiceCreate } from '@/types'

interface ThirdPartyServiceManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'

const STATUS_COLORS: Record<
  string,
  { bg: string; text: string; darkBg: string; darkText: string }
> = {
  active: {
    bg: 'bg-green-100',
    text: 'text-green-700',
    darkBg: 'bg-green-900/30',
    darkText: 'text-green-400',
  },
  deprecated: {
    bg: 'bg-yellow-100',
    text: 'text-yellow-700',
    darkBg: 'bg-yellow-900/30',
    darkText: 'text-yellow-400',
  },
  evaluating: {
    bg: 'bg-blue-100',
    text: 'text-blue-700',
    darkBg: 'bg-blue-900/30',
    darkText: 'text-blue-400',
  },
  inactive: {
    bg: 'bg-gray-100',
    text: 'text-gray-700',
    darkBg: 'bg-gray-700',
    darkText: 'text-gray-400',
  },
}

export function ThirdPartyServiceManagement({
  isDarkMode,
}: ThirdPartyServiceManagementProps) {
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedSlug, setSelectedSlug] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const orgSlug = selectedOrganization?.slug

  const {
    data: services = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['third-party-services', orgSlug],
    queryFn: () => listThirdPartyServices(orgSlug!),
    enabled: !!orgSlug,
  })

  const createMutation = useMutation({
    mutationFn: (svc: ThirdPartyServiceCreate) =>
      createThirdPartyService(orgSlug!, svc),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['third-party-services', orgSlug],
      })
      setViewMode('list')
      setSelectedSlug(null)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({
      slug,
      svc,
    }: {
      slug: string
      svc: ThirdPartyServiceCreate
    }) => updateThirdPartyService(orgSlug!, slug, svc),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['third-party-services', orgSlug],
      })
      setViewMode('list')
      setSelectedSlug(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: (slug: string) => deleteThirdPartyService(orgSlug!, slug),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['third-party-services', orgSlug],
      })
    },
    onError: (error: AxiosError<{ detail?: string }>) => {
      alert(
        `Failed to delete service: ${error.response?.data?.detail || error.message}`,
      )
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

  const handleDelete = (slug: string) => {
    const svc = services.find((s) => s.slug === slug)
    if (
      svc &&
      confirm(
        `Delete third-party service "${svc.name}"? This action cannot be undone.`,
      )
    ) {
      deleteMutation.mutate(slug)
    }
  }

  const handleSave = (svcData: ThirdPartyServiceCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(svcData)
    } else if (selectedSlug) {
      updateMutation.mutate({ slug: selectedSlug, svc: svcData })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedSlug(null)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading third-party services...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div
        className={`flex items-center gap-3 rounded-lg border p-4 ${
          isDarkMode
            ? 'border-red-700 bg-red-900/20 text-red-400'
            : 'border-red-200 bg-red-50 text-red-700'
        }`}
      >
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load third-party services</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ThirdPartyServiceForm
        service={selectedService}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedService) {
    return (
      <ThirdPartyServiceDetail
        service={selectedService}
        onEdit={() => {
          setSelectedSlug(selectedService.slug)
          setViewMode('edit')
        }}
        onBack={handleCancel}
        isDarkMode={isDarkMode}
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
              className={`absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}
            />
            <Input
              placeholder="Search services..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'border-gray-600 bg-gray-700 text-white' : ''}`}
            />
          </div>
        </div>
        <Button
          onClick={() => {
            setSelectedSlug(null)
            setViewMode('create')
          }}
          className="bg-[#2A4DD0] text-white hover:bg-blue-700"
        >
          <Plus className="mr-2 h-4 w-4" />
          New Service
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <div
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Total Services
          </div>
          <div
            className={`mt-1 text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            {filteredServices.length}
          </div>
        </div>
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <div
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Active
          </div>
          <div
            className={`mt-1 text-2xl ${isDarkMode ? 'text-green-400' : 'text-green-600'}`}
          >
            {statusCounts.active}
          </div>
        </div>
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <div
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Evaluating
          </div>
          <div
            className={`mt-1 text-2xl ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`}
          >
            {statusCounts.evaluating}
          </div>
        </div>
        <div
          className={`rounded-lg border p-4 ${
            isDarkMode
              ? 'border-gray-700 bg-gray-800'
              : 'border-gray-200 bg-white'
          }`}
        >
          <div
            className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Deprecated
          </div>
          <div
            className={`mt-1 text-2xl ${isDarkMode ? 'text-yellow-400' : 'text-yellow-600'}`}
          >
            {statusCounts.deprecated}
          </div>
        </div>
      </div>

      {/* Services Table */}
      <div
        className={`rounded-lg border ${
          isDarkMode
            ? 'border-gray-700 bg-gray-800'
            : 'border-gray-200 bg-white'
        }`}
      >
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead
              className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
            >
              <tr>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Service
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Vendor
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Category
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Status
                </th>
                <th
                  className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Team
                </th>
                <th
                  className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                    isDarkMode ? 'text-gray-400' : 'text-gray-500'
                  }`}
                >
                  Actions
                </th>
              </tr>
            </thead>
            <tbody
              className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}
            >
              {filteredServices.map((svc) => {
                const statusColor =
                  STATUS_COLORS[svc.status] || STATUS_COLORS.inactive
                return (
                  <tr
                    key={svc.slug}
                    onClick={() => {
                      setSelectedSlug(svc.slug)
                      setViewMode('detail')
                    }}
                    onKeyDown={(e) => {
                      if (e.currentTarget !== e.target) return
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault()
                        setSelectedSlug(svc.slug)
                        setViewMode('detail')
                      }
                    }}
                    tabIndex={0}
                    aria-label={`View service ${svc.name}`}
                    className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700/50' : 'hover:bg-gray-50'}`}
                  >
                    <td className="px-6 py-4">
                      <div className="flex items-center gap-3">
                        <div
                          className={`flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-lg ${
                            isDarkMode ? 'bg-purple-900/30' : 'bg-purple-50'
                          }`}
                        >
                          {svc.icon ? (
                            <img
                              src={svc.icon}
                              alt=""
                              className="h-5 w-5 rounded object-cover"
                            />
                          ) : (
                            <Cloud
                              className={`h-4 w-4 ${isDarkMode ? 'text-purple-400' : 'text-purple-600'}`}
                            />
                          )}
                        </div>
                        <div>
                          <div
                            className={
                              isDarkMode ? 'text-white' : 'text-gray-900'
                            }
                          >
                            {svc.name}
                          </div>
                          {svc.description && (
                            <div
                              className={`max-w-xs truncate text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                            >
                              {svc.description}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td
                      className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                    >
                      {svc.vendor}
                    </td>
                    <td
                      className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                    >
                      {svc.category || (
                        <span
                          className={
                            isDarkMode ? 'text-gray-500' : 'text-gray-400'
                          }
                        >
                          --
                        </span>
                      )}
                    </td>
                    <td className="px-6 py-4">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          isDarkMode
                            ? `${statusColor.darkBg} ${statusColor.darkText}`
                            : `${statusColor.bg} ${statusColor.text}`
                        }`}
                      >
                        {svc.status}
                      </span>
                    </td>
                    <td
                      className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}
                    >
                      {svc.team?.name || (
                        <span
                          className={
                            isDarkMode ? 'text-gray-500' : 'text-gray-400'
                          }
                        >
                          --
                        </span>
                      )}
                    </td>
                    <td
                      className="px-6 py-4 text-right"
                      onClick={(e) => e.stopPropagation()}
                      onKeyDown={(e) => e.stopPropagation()}
                    >
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="ghost"
                          size="sm"
                          aria-label={`Delete service ${svc.name}`}
                          onClick={() => handleDelete(svc.slug)}
                          disabled={deleteMutation.isPending}
                          className={
                            isDarkMode
                              ? 'text-red-400 hover:bg-red-900/20 hover:text-red-300'
                              : 'text-red-600 hover:bg-red-50 hover:text-red-700'
                          }
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>

          {filteredServices.length === 0 && (
            <div
              className={`py-12 text-center ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
            >
              {searchQuery
                ? 'No services found matching your search.'
                : selectedOrganization
                  ? `No third-party services in ${selectedOrganization.name} yet.`
                  : 'No third-party services created yet.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
