import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Trash2, Layers, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { ProjectTypeForm } from './project-types/ProjectTypeForm'
import { ProjectTypeDetail } from './project-types/ProjectTypeDetail'
import { useOrganization } from '@/contexts/OrganizationContext'
import { listProjectTypes, deleteProjectType, createProjectType, updateProjectType } from '@/api/endpoints'
import type { ProjectTypeCreate } from '@/types'

interface ProjectTypeManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'

export function ProjectTypeManagement({ isDarkMode }: ProjectTypeManagementProps) {
  const queryClient = useQueryClient()
  const { selectedOrganization } = useOrganization()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedPtSlug, setSelectedPtSlug] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const { data: projectTypes = [], isLoading, error } = useQuery({
    queryKey: ['projectTypes'],
    queryFn: listProjectTypes,
  })

  const createMutation = useMutation({
    mutationFn: createProjectType,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projectTypes'] })
      setViewMode('list')
      setSelectedPtSlug(null)
    },
  })

  const updateMutation = useMutation({
    mutationFn: ({ slug, pt }: { slug: string; pt: ProjectTypeCreate }) =>
      updateProjectType(slug, pt),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projectTypes'] })
      setViewMode('list')
      setSelectedPtSlug(null)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: deleteProjectType,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['projectTypes'] })
    },
    onError: (error: any) => {
      alert(`Failed to delete project type: ${error.response?.data?.detail || error.message}`)
    },
  })

  // Filter by selected org and search
  const filteredProjectTypes = projectTypes.filter((pt) => {
    if (selectedOrganization && pt.organization.slug !== selectedOrganization.slug) {
      return false
    }
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        pt.name.toLowerCase().includes(query) ||
        pt.slug.toLowerCase().includes(query) ||
        (pt.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const selectedProjectType = useMemo(
    () => projectTypes.find((pt) => pt.slug === selectedPtSlug) || null,
    [projectTypes, selectedPtSlug],
  )

  const orgCount = useMemo(
    () => new Set(filteredProjectTypes.map((pt) => pt.organization.slug)).size,
    [filteredProjectTypes],
  )

  const handleDelete = (slug: string) => {
    const pt = projectTypes.find((p) => p.slug === slug)
    if (pt && confirm(`Delete project type "${pt.name}"? This action cannot be undone.`)) {
      deleteMutation.mutate(slug)
    }
  }

  const handleSave = (ptData: ProjectTypeCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(ptData)
    } else if (selectedPtSlug) {
      updateMutation.mutate({ slug: selectedPtSlug, pt: ptData })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedPtSlug(null)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading project types...
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
          <div className="font-medium">Failed to load project types</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ProjectTypeForm
        projectType={selectedProjectType}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedProjectType) {
    return (
      <ProjectTypeDetail
        projectType={selectedProjectType}
        onEdit={() => {
          setSelectedPtSlug(selectedProjectType.slug)
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
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
              isDarkMode ? 'text-gray-400' : 'text-gray-500'
            }`} />
            <Input
              placeholder="Search project types..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-10 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
          </div>
        </div>
        <Button
          onClick={() => {
            setSelectedPtSlug(null)
            setViewMode('create')
          }}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
        >
          <Plus className="w-4 h-4 mr-2" />
          New Project Type
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className={`p-4 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Total Project Types
          </div>
          <div className={`mt-1 text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {filteredProjectTypes.length}
          </div>
        </div>
        <div className={`p-4 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Organizations
          </div>
          <div className={`mt-1 text-2xl ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {orgCount}
          </div>
        </div>
      </div>

      {/* Project Types Table */}
      <div className={`rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className={`border-b ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}>
              <tr>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Project Type
                </th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Slug
                </th>
                <th className={`px-6 py-3 text-left text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Organization
                </th>
                <th className={`px-6 py-3 text-right text-xs uppercase tracking-wider ${
                  isDarkMode ? 'text-gray-400' : 'text-gray-500'
                }`}>
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className={`divide-y ${isDarkMode ? 'divide-gray-700' : 'divide-gray-200'}`}>
              {filteredProjectTypes.map((pt) => (
                <tr
                  key={pt.slug}
                  onClick={() => {
                    setSelectedPtSlug(pt.slug)
                    setViewMode('detail')
                  }}
                  onKeyDown={(e) => {
                    if (e.currentTarget !== e.target) return
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setSelectedPtSlug(pt.slug)
                      setViewMode('detail')
                    }
                  }}
                  tabIndex={0}
                  aria-label={`View project type ${pt.name}`}
                  className={`cursor-pointer ${isDarkMode ? 'hover:bg-gray-700/50' : 'hover:bg-gray-50'}`}
                >
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-3">
                      <div className={`w-8 h-8 rounded-lg flex items-center justify-center flex-shrink-0 ${
                        isDarkMode ? 'bg-purple-900/30' : 'bg-purple-50'
                      }`}>
                        {pt.icon ? (
                          <img src={pt.icon} alt="" className="w-5 h-5 rounded object-cover" />
                        ) : (
                          <Layers className={`w-4 h-4 ${isDarkMode ? 'text-purple-400' : 'text-purple-600'}`} />
                        )}
                      </div>
                      <div>
                        <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                          {pt.name}
                        </div>
                        {pt.description && (
                          <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                            {pt.description}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                    <code className={`px-2 py-1 rounded ${
                      isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
                    }`}>
                      {pt.slug}
                    </code>
                  </td>
                  <td className={`px-6 py-4 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-600'}`}>
                    {pt.organization.name}
                  </td>
                  <td className="px-6 py-4 text-right" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        aria-label={`Delete project type ${pt.name}`}
                        onClick={() => handleDelete(pt.slug)}
                        disabled={deleteMutation.isPending}
                        className={isDarkMode ? 'text-red-400 hover:text-red-300 hover:bg-red-900/20' : 'text-red-600 hover:text-red-700 hover:bg-red-50'}
                      >
                        <Trash2 className="w-4 h-4" />
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          {filteredProjectTypes.length === 0 && (
            <div className={`text-center py-12 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
              {searchQuery
                ? 'No project types found matching your search.'
                : selectedOrganization
                  ? `No project types in ${selectedOrganization.name} yet.`
                  : 'No project types created yet.'}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
