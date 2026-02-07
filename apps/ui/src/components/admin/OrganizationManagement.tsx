import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Edit2, Trash2, Building2, AlertCircle } from 'lucide-react'
import { Button } from '../ui/button'
import { Input } from '../ui/input'
import { OrganizationForm } from './organizations/OrganizationForm'
import { OrganizationDetail } from './organizations/OrganizationDetail'
import {
  listOrganizations,
  deleteOrganization,
  createOrganization,
  updateOrganization
} from '@/api/endpoints'
import type { OrganizationCreate } from '@/types'

interface OrganizationManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'

export function OrganizationManagement({ isDarkMode }: OrganizationManagementProps) {
  const queryClient = useQueryClient()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedOrgSlug, setSelectedOrgSlug] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const { data: organizations = [], isLoading, error } = useQuery({
    queryKey: ['organizations'],
    queryFn: listOrganizations,
  })

  const createMutation = useMutation({
    mutationFn: createOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
      setViewMode('list')
      setSelectedOrgSlug(null)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ slug, org }: { slug: string; org: OrganizationCreate }) =>
      updateOrganization(slug, org),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
      setViewMode('list')
      setSelectedOrgSlug(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteOrganization,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['organizations'] })
    },
    onError: (error: any) => {
      alert(`Failed to delete organization: ${error.response?.data?.detail || error.message}`)
    },
  })

  const filteredOrgs = organizations.filter((org) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        org.name.toLowerCase().includes(query) ||
        org.slug.toLowerCase().includes(query) ||
        (org.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedOrg = organizations.find((o) => o.slug === selectedOrgSlug) || null

  const handleDelete = (slug: string) => {
    const org = organizations.find((o) => o.slug === slug)
    if (org && confirm(`Delete organization "${org.name}"? This action cannot be undone.`)) {
      deleteMutation.mutate(slug)
    }
  }

  const handleSave = (orgData: OrganizationCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(orgData)
    } else if (selectedOrgSlug) {
      updateMutation.mutate({ slug: selectedOrgSlug, org: orgData })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedOrgSlug(null)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading organizations...
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load organizations</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <OrganizationForm
        organization={selectedOrg}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedOrg) {
    return (
      <OrganizationDetail
        organization={selectedOrg}
        onEdit={() => {
          setSelectedOrgSlug(selectedOrg.slug)
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
        <div>
          <h2 className={`text-xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Organizations
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Manage organizations and their settings
          </p>
        </div>
        <Button
          onClick={() => {
            setSelectedOrgSlug(null)
            setViewMode('create')
          }}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white gap-2"
        >
          <Plus className="w-4 h-4" />
          Add Organization
        </Button>
      </div>

      {/* Search */}
      <div className={`flex items-center gap-4 p-4 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div className="flex-1 min-w-[300px]">
          <div className="relative">
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
              isDarkMode ? 'text-gray-400' : 'text-gray-500'
            }`} />
            <Input
              placeholder="Search organizations..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-9 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
          </div>
        </div>
      </div>

      {/* Organizations Grid */}
      {filteredOrgs.length === 0 ? (
        <div className={`p-12 rounded-lg border text-center ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <Building2 className={`w-8 h-8 mx-auto mb-2 ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`} />
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
            {searchQuery ? 'No organizations match your search' : 'No organizations created yet'}
          </div>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {filteredOrgs.map((org) => (
            <div
              key={org.slug}
              onClick={() => {
                setSelectedOrgSlug(org.slug)
                setViewMode('detail')
              }}
              className={`p-6 rounded-lg border cursor-pointer transition-shadow hover:shadow-lg ${
                isDarkMode
                  ? 'bg-gray-800 border-gray-700 hover:border-blue-500'
                  : 'bg-white border-gray-200 hover:border-blue-300'
              }`}
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-start gap-3">
                  <div className={`w-12 h-12 rounded-lg flex items-center justify-center ${
                    isDarkMode ? 'bg-blue-900/30' : 'bg-blue-50'
                  }`}>
                    {org.icon_url ? (
                      <img src={org.icon_url} alt="" className="w-8 h-8 rounded object-cover" />
                    ) : (
                      <Building2 className={`w-6 h-6 ${isDarkMode ? 'text-blue-400' : 'text-blue-600'}`} />
                    )}
                  </div>
                  <div>
                    <h3 className={`font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                      {org.name}
                    </h3>
                    {org.description && (
                      <p className={`mt-1 text-sm line-clamp-2 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                        {org.description}
                      </p>
                    )}
                    <code className={`inline-block mt-2 px-2 py-1 rounded text-xs ${
                      isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-600'
                    }`}>
                      {org.slug}
                    </code>
                  </div>
                </div>
              </div>

              {/* Actions */}
              <div className="flex gap-2" onClick={(e) => e.stopPropagation()}>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => {
                    setSelectedOrgSlug(org.slug)
                    setViewMode('edit')
                  }}
                  className={isDarkMode ? 'border-gray-700 hover:bg-gray-700' : ''}
                >
                  <Edit2 className="w-3 h-3 mr-1" />
                  Edit
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => handleDelete(org.slug)}
                  disabled={deleteMutation.isPending}
                  className={isDarkMode ? 'border-gray-700 hover:bg-gray-700 text-red-400' : 'text-red-600'}
                >
                  <Trash2 className="w-3 h-3 mr-1" />
                  Delete
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Summary */}
      {filteredOrgs.length > 0 && (
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Showing {filteredOrgs.length} of {organizations.length} organization(s)
        </div>
      )}
    </div>
  )
}
