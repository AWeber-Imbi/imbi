import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus, Search, Edit2, Trash2, FileJson, AlertCircle,
  CheckCircle, XCircle
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { BlueprintForm } from './blueprints/BlueprintForm'
import { BlueprintDetail } from './blueprints/BlueprintDetail'
import { useOpenApiSpec, getSchemaEnum } from '@/api/openapi'
import {
  listBlueprints, deleteBlueprint, createBlueprint, updateBlueprint,
  refreshBlueprintSchemas
} from '@/api/endpoints'
import type { Blueprint, BlueprintCreate } from '@/types'

interface BlueprintManagementProps {
  isDarkMode: boolean
}

type ViewMode = 'list' | 'create' | 'edit' | 'detail'

interface BlueprintKey {
  type: string
  slug: string
}

const TYPE_COLORS = [
  'purple', 'blue', 'green', 'orange', 'pink', 'cyan', 'amber', 'rose'
]

const TYPE_COLOR_CLASSES: Record<string, { light: string; dark: string }> = {
  purple: {
    light: 'bg-purple-100 text-purple-700',
    dark: 'bg-purple-900/30 text-purple-400',
  },
  blue: {
    light: 'bg-blue-100 text-blue-700',
    dark: 'bg-blue-900/30 text-blue-400',
  },
  green: {
    light: 'bg-green-100 text-green-700',
    dark: 'bg-green-900/30 text-green-400',
  },
  orange: {
    light: 'bg-orange-100 text-orange-700',
    dark: 'bg-orange-900/30 text-orange-400',
  },
  pink: {
    light: 'bg-pink-100 text-pink-700',
    dark: 'bg-pink-900/30 text-pink-400',
  },
  cyan: {
    light: 'bg-cyan-100 text-cyan-700',
    dark: 'bg-cyan-900/30 text-cyan-400',
  },
  amber: {
    light: 'bg-amber-100 text-amber-700',
    dark: 'bg-amber-900/30 text-amber-400',
  },
  rose: {
    light: 'bg-rose-100 text-rose-700',
    dark: 'bg-rose-900/30 text-rose-400',
  },
}

export function getTypeColor(type: string, allTypes: string[]): string {
  const idx = allTypes.indexOf(type)
  return TYPE_COLORS[(idx >= 0 ? idx : 0) % TYPE_COLORS.length]
}

export function getTypeBadgeClasses(
  type: string,
  allTypes: string[],
  isDarkMode: boolean
): string {
  const color = getTypeColor(type, allTypes)
  const classes = TYPE_COLOR_CLASSES[color] || TYPE_COLOR_CLASSES.blue
  return isDarkMode ? classes.dark : classes.light
}

export function BlueprintManagement({ isDarkMode }: BlueprintManagementProps) {
  const queryClient = useQueryClient()
  const [viewMode, setViewMode] = useState<ViewMode>('list')
  const [selectedKey, setSelectedKey] = useState<BlueprintKey | null>(null)
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [enabledFilter, setEnabledFilter] = useState<string>('')

  // Fetch blueprints
  const { data: blueprints = [], isLoading, error } = useQuery({
    queryKey: ['blueprints'],
    queryFn: () => listBlueprints(),
  })

  // Fetch blueprint types from OpenAPI spec
  const { data: openApiSpec } = useOpenApiSpec()
  const blueprintTypes = openApiSpec
    ? getSchemaEnum(openApiSpec, 'Blueprint', 'type')
    : []

  // Refresh backend schema cache and frontend queries after mutations
  const invalidateAfterMutation = async () => {
    queryClient.invalidateQueries({ queryKey: ['blueprints'] })
    queryClient.invalidateQueries({ queryKey: ['blueprint'] })
    // Refresh the backend's cached blueprint-enhanced OpenAPI models
    try {
      await refreshBlueprintSchemas()
    } catch {
      // Non-critical — the schema cache will be stale until next restart
    }
    queryClient.invalidateQueries({ queryKey: ['openapi-spec'] })
  }

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: ({ type, slug }: BlueprintKey) => deleteBlueprint(type, slug),
    onSuccess: () => {
      invalidateAfterMutation()
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onError: (error: any) => {
      alert(
        `Failed to delete blueprint: ${error.response?.data?.detail || error.message}`
      )
    },
  })

  // Create mutation
  const createMutation = useMutation({
    mutationFn: (blueprint: BlueprintCreate) => createBlueprint(blueprint),
    onSuccess: () => {
      invalidateAfterMutation()
      setViewMode('list')
      setSelectedKey(null)
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onError: (error: any) => {
      console.error('Failed to create blueprint:', error)
    },
  })

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: ({
      type,
      slug,
      blueprint,
    }: {
      type: string
      slug: string
      blueprint: BlueprintCreate
    }) => updateBlueprint(type, slug, blueprint),
    onSuccess: () => {
      invalidateAfterMutation()
      setViewMode('list')
      setSelectedKey(null)
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    onError: (error: any) => {
      console.error('Failed to update blueprint:', error)
    },
  })

  // Filter blueprints
  const filteredBlueprints = blueprints.filter((bp: Blueprint) => {
    if (searchQuery) {
      const query = searchQuery.toLowerCase()
      const matchesName = bp.name.toLowerCase().includes(query)
      const matchesDesc = bp.description?.toLowerCase().includes(query) ?? false
      if (!matchesName && !matchesDesc) return false
    }
    if (typeFilter && bp.type !== typeFilter) return false
    if (enabledFilter === 'enabled' && !bp.enabled) return false
    if (enabledFilter === 'disabled' && bp.enabled) return false
    return true
  })

  // Check for priority conflicts
  const priorityConflicts = (type: string, priority: number, excludeSlug?: string) => {
    return blueprints.filter(
      (bp: Blueprint) =>
        bp.type === type &&
        bp.priority === priority &&
        bp.slug !== excludeSlug
    )
  }

  const handleDelete = (key: BlueprintKey) => {
    if (
      confirm(
        'Are you sure you want to delete this blueprint? This action cannot be undone.'
      )
    ) {
      deleteMutation.mutate(key)
    }
  }

  const handleCreateClick = () => {
    setSelectedKey(null)
    setViewMode('create')
  }

  const handleEditClick = (key: BlueprintKey) => {
    setSelectedKey(key)
    setViewMode('edit')
  }

  const handleViewClick = (key: BlueprintKey) => {
    setSelectedKey(key)
    setViewMode('detail')
  }

  const handleSave = (data: BlueprintCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(data)
    } else if (selectedKey) {
      updateMutation.mutate({
        type: selectedKey.type,
        slug: selectedKey.slug,
        blueprint: data,
      })
    }
  }

  const handleCancel = () => {
    setViewMode('list')
    setSelectedKey(null)
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Loading blueprints...
        </div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div
        className={`flex items-center gap-3 p-4 rounded-lg border ${
          isDarkMode
            ? 'bg-red-900/20 border-red-700 text-red-400'
            : 'bg-red-50 border-red-200 text-red-700'
        }`}
      >
        <AlertCircle className="w-5 h-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load blueprints</div>
          <div className="text-sm mt-1">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  // View mode: Create or Edit
  if (viewMode === 'create' || viewMode === 'edit') {
    const isCreate = viewMode === 'create'
    return (
      <BlueprintForm
        key={selectedKey ? `${selectedKey.type}/${selectedKey.slug}` : 'create'}
        blueprintKey={selectedKey}
        blueprintTypes={blueprintTypes}
        onSave={handleSave}
        onCancel={handleCancel}
        isDarkMode={isDarkMode}
        isLoading={
          isCreate ? createMutation.isPending : updateMutation.isPending
        }
        error={isCreate ? createMutation.error : updateMutation.error}
        checkPriorityConflict={priorityConflicts}
      />
    )
  }

  // View mode: Detail
  if (viewMode === 'detail' && selectedKey) {
    return (
      <BlueprintDetail
        key={`${selectedKey.type}/${selectedKey.slug}`}
        blueprintKey={selectedKey}
        blueprintTypes={blueprintTypes}
        onEdit={() => handleEditClick(selectedKey)}
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
          <h2
            className={`text-xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
          >
            Blueprints
          </h2>
          <p
            className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
          >
            Define metadata schemas for projects and other entities
          </p>
        </div>
        <Button
          onClick={handleCreateClick}
          className="bg-[#2A4DD0] hover:bg-blue-700 text-white gap-2"
        >
          <Plus className="w-4 h-4" />
          Create Blueprint
        </Button>
      </div>

      {/* Filters */}
      <div
        className={`flex flex-wrap items-center gap-4 p-4 rounded-lg border ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <div className="flex-1 min-w-[300px]">
          <div className="relative">
            <Search
              className={`absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 ${
                isDarkMode ? 'text-gray-400' : 'text-gray-500'
              }`}
            />
            <Input
              placeholder="Search by name or description..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className={`pl-9 ${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}`}
            />
          </div>
        </div>
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className={`px-3 py-2 rounded-lg border text-sm ${
            isDarkMode
              ? 'bg-gray-700 border-gray-600 text-white'
              : 'bg-white border-gray-300 text-gray-900'
          }`}
        >
          <option value="">All Types</option>
          {blueprintTypes.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <select
          value={enabledFilter}
          onChange={(e) => setEnabledFilter(e.target.value)}
          className={`px-3 py-2 rounded-lg border text-sm ${
            isDarkMode
              ? 'bg-gray-700 border-gray-600 text-white'
              : 'bg-white border-gray-300 text-gray-900'
          }`}
        >
          <option value="">All Status</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
        </select>
      </div>

      {/* Blueprints Table */}
      <div
        className={`rounded-lg border overflow-hidden ${
          isDarkMode
            ? 'bg-gray-800 border-gray-700'
            : 'bg-white border-gray-200'
        }`}
      >
        <table className="w-full">
          <thead
            className={`${isDarkMode ? 'bg-gray-750 border-b border-gray-700' : 'bg-gray-50 border-b border-gray-200'}`}
          >
            <tr>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Name
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Slug
              </th>
              <th
                className={`px-4 py-3 text-left text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Type
              </th>
              <th
                className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Enabled
              </th>
              <th
                className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Priority
              </th>
              <th
                className={`px-4 py-3 text-center text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Version
              </th>
              <th
                className={`px-4 py-3 text-right text-xs font-medium ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
              >
                Actions
              </th>
            </tr>
          </thead>
          <tbody
            className={
              isDarkMode
                ? 'divide-y divide-gray-700'
                : 'divide-y divide-gray-200'
            }
          >
            {filteredBlueprints.length === 0 ? (
              <tr>
                <td colSpan={7} className="px-4 py-12 text-center">
                  <div
                    className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                  >
                    {searchQuery || typeFilter || enabledFilter
                      ? 'No blueprints match your filters'
                      : 'No blueprints created yet'}
                  </div>
                </td>
              </tr>
            ) : (
              filteredBlueprints.map((bp: Blueprint) => (
                <tr
                  key={`${bp.type}/${bp.slug}`}
                  onClick={() =>
                    handleViewClick({ type: bp.type, slug: bp.slug })
                  }
                  className={`cursor-pointer ${
                    isDarkMode ? 'hover:bg-gray-750' : 'hover:bg-gray-50'
                  }`}
                >
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <FileJson
                        className={`w-4 h-4 flex-shrink-0 ${
                          isDarkMode ? 'text-blue-400' : 'text-blue-600'
                        }`}
                      />
                      <div>
                        <span
                          className={`text-sm font-medium ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
                        >
                          {bp.name}
                        </span>
                        {bp.description && (
                          <div
                            className={`text-xs mt-0.5 ${isDarkMode ? 'text-gray-400' : 'text-gray-500'}`}
                          >
                            {bp.description}
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className={`px-4 py-3 text-sm font-mono ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                    {bp.slug}
                  </td>
                  <td className="px-4 py-3">
                    <span
                      className={`inline-flex items-center px-2 py-1 rounded text-xs font-medium ${getTypeBadgeClasses(bp.type, blueprintTypes, isDarkMode)}`}
                    >
                      {bp.type}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-center">
                    {bp.enabled ? (
                      <CheckCircle
                        className={`w-4 h-4 mx-auto ${isDarkMode ? 'text-green-400' : 'text-green-600'}`}
                      />
                    ) : (
                      <XCircle
                        className={`w-4 h-4 mx-auto ${isDarkMode ? 'text-gray-500' : 'text-gray-400'}`}
                      />
                    )}
                  </td>
                  <td
                    className={`px-4 py-3 text-center text-sm ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}
                  >
                    {bp.priority}
                  </td>
                  <td
                    className={`px-4 py-3 text-center text-sm font-mono ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                  >
                    v{bp.version}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center justify-end gap-2">
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleEditClick({
                            type: bp.type,
                            slug: bp.slug,
                          })
                        }}
                        className={`p-1.5 rounded ${
                          isDarkMode
                            ? 'text-gray-400 hover:text-gray-200 hover:bg-gray-700'
                            : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                        }`}
                        title="Edit"
                      >
                        <Edit2 className="w-4 h-4" />
                      </button>
                      <button
                        onClick={(e) => {
                          e.stopPropagation()
                          handleDelete({ type: bp.type, slug: bp.slug })
                        }}
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
      {filteredBlueprints.length > 0 && (
        <div
          className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
        >
          Showing {filteredBlueprints.length} of {blueprints.length}{' '}
          blueprint(s)
        </div>
      )}
    </div>
  )
}
