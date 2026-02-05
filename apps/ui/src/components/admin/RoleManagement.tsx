import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Edit2, Trash2, Eye, Shield, AlertCircle, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { RoleForm } from './roles/RoleForm'
import { RoleDetail } from './roles/RoleDetail'
import { getRoles, deleteRole, createRole, updateRole } from '@/api/endpoints'
import type { RoleDetail as RoleDetailType, RoleCreate } from '@/types'

interface RoleManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'

export function RoleManagement({ isDarkMode }: RoleManagementProps) {
  const queryClient = useQueryClient()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedRoleSlug, setSelectedRoleSlug] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  // Fetch roles from API
  const { data: roles = [], isLoading, error } = useQuery({
    queryKey: ['roles'],
    queryFn: getRoles,
  })

  // Delete role mutation
  const deleteMutation = useMutation({
    mutationFn: deleteRole,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] })
    },
    onError: (error: any) => {
      alert(`Failed to delete role: ${error.response?.data?.detail || error.message}`)
    }
  })

  // Create role mutation
  const createMutation = useMutation({
    mutationFn: createRole,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] })
      setViewMode('list')
      setSelectedRoleSlug(null)
    },
    onError: (error: any) => {
      console.error('Failed to create role:', error)
    }
  })

  // Update role mutation
  const updateMutation = useMutation({
    mutationFn: ({ slug, role }: { slug: string, role: RoleCreate }) =>
      updateRole(slug, role),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['roles'] })
      setViewMode('list')
      setSelectedRoleSlug(null)
    },
    onError: (error: any) => {
      console.error('Failed to update role:', error)
    }
  })

  // Filter roles locally
  const filteredRoles = roles.filter(role => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        role.name.toLowerCase().includes(query) ||
        role.slug.toLowerCase().includes(query) ||
        (role.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const handleDelete = (slug: string) => {
    if (confirm('Are you sure you want to delete this role? This action cannot be undone.')) {
      deleteMutation.mutate(slug)
    }
  }

  const handleCreateClick = () => {
    setSelectedRoleSlug(null)
    setViewMode('create')
  }

  const handleEditClick = (slug: string) => {
    setSelectedRoleSlug(slug)
    setViewMode('edit')
  }

  const handleViewClick = (slug: string) => {
    setSelectedRoleSlug(slug)
    setViewMode('detail')
  }

  const handleSave = (roleData: RoleCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(roleData)
    } else if (selectedRoleSlug) {
      updateMutation.mutate({ slug: selectedRoleSlug, role: roleData })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedRoleSlug(null)
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading roles...
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className={`flex items-center gap-3 p-4 rounded-lg border ${
        isDarkMode ? 'bg-red-900/20 border-red-700 text-red-400' : 'bg-red-50 border-red-200 text-red-700'
      }`}>
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load roles</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  // View mode: Create or Edit
  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <RoleForm
        roleSlug={selectedRoleSlug}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending || updateMutation.isPending}
        error={createMutation.error || updateMutation.error}
      />
    )
  }

  // View mode: Detail
  if (viewMode === 'detail' && selectedRoleSlug) {
    return (
      <RoleDetail
        slug={selectedRoleSlug}
        onEdit={() => handleEditClick(selectedRoleSlug)}
        onBack={handleCancel}
        isDarkMode={isDarkMode}
      />
    )
  }

  // View mode: List (default)
  return (
    <div className="space-y-6">
      {/* Header with Actions */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Roles
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Define roles and manage permission collections
          </p>
        </div>
        <Button
          onClick={handleCreateClick}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white gap-2"
        >
          <Plus className="w-4 h-4" />
          Create New Role
        </Button>
      </div>

      {/* Search */}
      <div className={`flex flex-wrap items-center gap-4 p-4 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <div className="flex-1 min-w-[300px]">
          <div className="relative">
            <Search className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
              isDarkMode ? 'text-gray-400' : 'text-gray-500'
            }`} />
            <Input
              placeholder="Search by name, slug, or description..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-9 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
          </div>
        </div>
      </div>

      {/* Roles Table */}
      <div className={`rounded-lg border overflow-hidden ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <table className="w-full">
          <thead className={`${isDarkMode ? 'bg-gray-750 border-b border-gray-700' : 'bg-gray-50 border-b border-gray-200'}`}>
            <tr>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Role
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Slug
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Description
              </th>
              <th className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Type
              </th>
              <th className={`px-4 py-3 text-right text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Actions
              </th>
            </tr>
          </thead>
          <tbody className={isDarkMode ? 'divide-y divide-gray-700' : 'divide-y divide-gray-200'}>
            {filteredRoles.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center">
                  <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                    {searchQuery
                      ? 'No roles match your search'
                      : 'No roles created yet'}
                  </div>
                </td>
              </tr>
            ) : (
              filteredRoles.map((role) => {
                const isSystem = 'is_system' in role && (role as RoleDetailType).is_system
                return (
                  <tr
                    key={role.slug}
                    className={isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'}
                  >
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Shield className={`w-4 h-4 flex-shrink-0 ${
                          isDarkMode ? 'text-blue-400' : 'text-blue-600'
                        }`} />
                        <span className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                          {role.name}
                        </span>
                      </div>
                    </td>
                    <td className={`px-4 py-3 text-sm font-mono ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                      {role.slug}
                    </td>
                    <td className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                      {role.description || '-'}
                    </td>
                    <td className="px-4 py-3 text-center">
                      {isSystem ? (
                        <span className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-amber-900/30 text-amber-400' : 'bg-amber-100 text-amber-700'
                        }`}>
                          <Lock className="w-3 h-3" />
                          System
                        </span>
                      ) : (
                        <span className={`px-2 py-1 rounded text-xs font-medium ${
                          isDarkMode ? 'bg-blue-900/30 text-blue-400' : 'bg-blue-100 text-blue-700'
                        }`}>
                          Custom
                        </span>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => handleViewClick(role.slug)}
                          className={`p-1.5 rounded ${
                            isDarkMode ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                          }`}
                          title="View"
                        >
                          <Eye className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleEditClick(role.slug)}
                          disabled={isSystem}
                          className={`p-1.5 rounded ${
                            isSystem
                              ? 'opacity-40 cursor-not-allowed'
                              : isDarkMode
                                ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'
                                : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                          }`}
                          title={isSystem ? 'System roles cannot be edited' : 'Edit'}
                        >
                          <Edit2 className="w-4 h-4" />
                        </button>
                        <button
                          onClick={() => handleDelete(role.slug)}
                          disabled={deleteMutation.isPending || isSystem}
                          className={`p-1.5 rounded ${
                            isSystem
                              ? 'opacity-40 cursor-not-allowed'
                              : isDarkMode
                                ? 'text-red-400 hover:text-red-300 hover:bg-gray-700'
                                : 'text-red-600 hover:text-red-700 hover:bg-gray-100'
                          }`}
                          title={isSystem ? 'System roles cannot be deleted' : 'Delete'}
                        >
                          <Trash2 className="w-4 h-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })
            )}
          </tbody>
        </table>
      </div>

      {/* Summary */}
      {filteredRoles.length > 0 && (
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Showing {filteredRoles.length} of {roles.length} role(s)
        </div>
      )}
    </div>
  )
}
