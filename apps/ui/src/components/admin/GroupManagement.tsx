import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Plus, Search, Edit2, Trash2, Eye, UsersRound, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { GroupForm } from './groups/GroupForm'
import { GroupDetail } from './groups/GroupDetail'
import { getGroups, deleteGroup, createGroup, updateGroup } from '@/api/endpoints'
import type { GroupCreate } from '@/types'

interface GroupManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'

export function GroupManagement({ isDarkMode }: GroupManagementProps) {
  const queryClient = useQueryClient()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedGroupSlug, setSelectedGroupSlug] = useState<string | null>(null)
  const [searchQuery, setSearchQuery] = useState('')

  const { data: groups = [], isLoading, error } = useQuery({
    queryKey: ['groups'],
    queryFn: getGroups,
  })

  const deleteMutation = useMutation({
    mutationFn: deleteGroup,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] })
    },
    onError: (error: any) => {
      alert(`Failed to delete group: ${error.response?.data?.detail || error.message}`)
    }
  })

  const createMutation = useMutation({
    mutationFn: createGroup,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] })
      setViewMode('list')
      setSelectedGroupSlug(null)
    },
    onError: (error: any) => {
      console.error('Failed to create group:', error)
    }
  })

  const updateMutation = useMutation({
    mutationFn: ({ slug, group }: { slug: string, group: GroupCreate }) =>
      updateGroup(slug, group),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['groups'] })
      setViewMode('list')
      setSelectedGroupSlug(null)
    },
    onError: (error: any) => {
      console.error('Failed to update group:', error)
    }
  })

  const filteredGroups = groups.filter(group => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      return (
        group.name.toLowerCase().includes(query) ||
        group.slug.toLowerCase().includes(query) ||
        (group.description?.toLowerCase().includes(query) ?? false)
      )
    }
    return true
  })

  const handleDelete = (slug: string) => {
    const group = groups.find(g => g.slug === slug)
    if (!group) return

    const warnings = []
    if (group.roles.length > 0) {
      warnings.push(`${group.roles.length} role assignment(s) will be removed`)
    }

    const message = warnings.length > 0
      ? `Delete group "${group.name}"?\n\n${warnings.join('\n')}`
      : `Delete group "${group.name}"?`

    if (confirm(message)) {
      deleteMutation.mutate(slug)
    }
  }

  const handleCreateClick = () => {
    setSelectedGroupSlug(null)
    setViewMode('create')
  }

  const handleEditClick = (slug: string) => {
    setSelectedGroupSlug(slug)
    setViewMode('edit')
  }

  const handleViewClick = (slug: string) => {
    setSelectedGroupSlug(slug)
    setViewMode('detail')
  }

  const handleSave = (groupData: GroupCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(groupData)
    } else if (selectedGroupSlug) {
      updateMutation.mutate({ slug: selectedGroupSlug, group: groupData })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedGroupSlug(null)
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Loading groups...
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
          <div className="font-medium">Failed to load groups</div>
          <div className="text-sm mt-1">{error instanceof Error ? error.message : 'An error occurred'}</div>
        </div>
      </div>
    )
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    const isCreate = viewMode === 'create'
    return (
      <GroupForm
        groupSlug={selectedGroupSlug}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={isCreate ? createMutation.isPending : updateMutation.isPending}
        error={isCreate ? createMutation.error : updateMutation.error}
      />
    )
  }

  if (viewMode === 'detail' && selectedGroupSlug) {
    return (
      <GroupDetail
        slug={selectedGroupSlug}
        onEdit={() => handleEditClick(selectedGroupSlug)}
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
            Groups
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Organize users into groups and assign roles collectively
          </p>
        </div>
        <Button
          onClick={handleCreateClick}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white gap-2"
        >
          <Plus className="w-4 h-4" />
          Create Group
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

      {/* Groups Table */}
      <div className={`rounded-lg border overflow-hidden ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <table className="w-full">
          <thead className={`${isDarkMode ? 'bg-gray-750 border-b border-gray-700' : 'bg-gray-50 border-b border-gray-200'}`}>
            <tr>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Group
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Slug
              </th>
              <th className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Description
              </th>
              <th className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Roles
              </th>
              <th className={`px-4 py-3 text-right text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Actions
              </th>
            </tr>
          </thead>
          <tbody className={isDarkMode ? 'divide-y divide-gray-700' : 'divide-y divide-gray-200'}>
            {filteredGroups.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-12 text-center">
                  {searchQuery ? (
                    <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                      No groups match your search
                    </div>
                  ) : (
                    <div>
                      <UsersRound className={`w-8 h-8 mx-auto mb-2 ${isDarkMode ? 'text-gray-600' : 'text-gray-300'}`} />
                      <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}>
                        No groups created yet
                      </div>
                      <div className={`text-xs mt-1 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                        Create your first group to organize users and assign roles
                      </div>
                    </div>
                  )}
                </td>
              </tr>
            ) : (
              filteredGroups.map((group) => (
                <tr
                  key={group.slug}
                  className={isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <UsersRound className={`w-4 h-4 flex-shrink-0 ${
                        isDarkMode ? 'text-blue-400' : 'text-blue-600'
                      }`} />
                      <span className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                        {group.name}
                      </span>
                    </div>
                    {group.parent && (
                      <div className={`text-xs mt-0.5 ml-6 ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}>
                        Parent: {group.parent.name}
                      </div>
                    )}
                  </td>
                  <td className={`px-4 py-3 text-sm font-mono ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    {group.slug}
                  </td>
                  <td className={`px-4 py-3 text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                    {group.description || '-'}
                  </td>
                  <td className="px-4 py-3 text-center">
                    <span className={`text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                      {group.roles.length}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={() => handleViewClick(group.slug)}
                        className={`p-1.5 rounded ${
                          isDarkMode ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                        }`}
                        title="View"
                      >
                        <Eye className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleEditClick(group.slug)}
                        className={`p-1.5 rounded ${
                          isDarkMode ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                        }`}
                        title="Edit"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={() => handleDelete(group.slug)}
                        disabled={deleteMutation.isPending}
                        className={`p-1.5 rounded ${
                          isDarkMode
                            ? 'text-red-400 hover:text-red-300 hover:bg-gray-700'
                            : 'text-red-600 hover:text-red-700 hover:bg-gray-100'
                        }`}
                        title="Delete"
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {/* Summary */}
      {filteredGroups.length > 0 && (
        <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
          Showing {filteredGroups.length} of {groups.length} group(s)
        </div>
      )}
    </div>
  )
}
