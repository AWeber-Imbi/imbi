/* eslint-disable react-refresh/only-export-components */
import React from 'react'
import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Search,
  Edit2,
  Trash2,
  FileJson,
  AlertCircle,
  CheckCircle,
  XCircle,
  Upload,
  Filter,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { BlueprintForm } from './blueprints/BlueprintForm'
import { BlueprintDetail } from './blueprints/BlueprintDetail'
import { ImportBlueprintDialog } from './blueprints/ImportBlueprintDialog'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useOpenApiSpec, getSchemaEnum } from '@/api/openapi'
import {
  listBlueprints,
  deleteBlueprint,
  createBlueprint,
  updateBlueprint,
} from '@/api/endpoints'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { Blueprint, BlueprintCreate } from '@/types'

interface BlueprintManagementProps {
  isDarkMode: boolean
}

interface BlueprintKey {
  type: string
  slug: string
}

const TYPE_COLORS = [
  'purple',
  'blue',
  'green',
  'orange',
  'pink',
  'cyan',
  'amber',
  'rose',
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
  isDarkMode: boolean,
): string {
  const color = getTypeColor(type, allTypes)
  const classes = TYPE_COLOR_CLASSES[color] || TYPE_COLOR_CLASSES.blue
  return isDarkMode ? classes.dark : classes.light
}

function renderFilterCell(
  filter: string | null | undefined,
  isDarkMode: boolean,
): React.ReactNode {
  const f = parseFilterFromBlueprint(filter)
  if (!f) return null
  const title = [
    f.project_type?.length ? `Project Types: ${f.project_type.join(', ')}` : '',
    f.environment?.length ? `Environments: ${f.environment.join(', ')}` : '',
  ]
    .filter(Boolean)
    .join('\n')
  return (
    <span title={title}>
      <Filter
        className={`mx-auto h-4 w-4 ${isDarkMode ? 'text-amber-400' : 'text-amber-600'}`}
      />
    </span>
  )
}

export function BlueprintManagement({ isDarkMode }: BlueprintManagementProps) {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedSlug,
    goToList,
    goToCreate,
    goToDetail,
    goToEdit,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const [typeFilter, setTypeFilter] = useState<string>('')
  const [enabledFilter, setEnabledFilter] = useState<string>('')
  const [importDialogOpen, setImportDialogOpen] = useState(false)

  // Parse compound key from URL slug (format: "type:slug")
  const selectedKey = useMemo<BlueprintKey | null>(() => {
    if (!selectedSlug) return null
    const colonIdx = selectedSlug.indexOf(':')
    if (colonIdx === -1) return null
    return {
      type: selectedSlug.substring(0, colonIdx),
      slug: selectedSlug.substring(colonIdx + 1),
    }
  }, [selectedSlug])

  // Fetch blueprints
  const {
    data: blueprints = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['blueprints'],
    queryFn: () => listBlueprints(),
  })

  // Fetch blueprint types from OpenAPI spec
  const { data: openApiSpec } = useOpenApiSpec()
  const blueprintTypes = openApiSpec
    ? getSchemaEnum(openApiSpec, 'Blueprint', 'type')
    : []

  // Refresh frontend queries after mutations
  // The backend auto-refreshes its OpenAPI schema cache on blueprint CRUD
  const invalidateAfterMutation = () => {
    queryClient.invalidateQueries({ queryKey: ['blueprints'] })
    queryClient.invalidateQueries({ queryKey: ['blueprint'] })
    queryClient.invalidateQueries({ queryKey: ['openapi-spec'] })
    queryClient.invalidateQueries({ queryKey: ['teamSchema'] })
    queryClient.invalidateQueries({ queryKey: ['environmentSchema'] })
    queryClient.invalidateQueries({ queryKey: ['projectTypeSchema'] })
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
        `Failed to delete blueprint: ${error.response?.data?.detail || error.message}`,
      )
    },
  })

  // Create mutation
  const createMutation = useMutation({
    mutationFn: (blueprint: BlueprintCreate) => createBlueprint(blueprint),
    onSuccess: () => {
      invalidateAfterMutation()
      goToList()
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
      goToList()
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

  const handleDelete = (key: BlueprintKey) => {
    if (
      confirm(
        'Are you sure you want to delete this blueprint? This action cannot be undone.',
      )
    ) {
      deleteMutation.mutate(key)
    }
  }

  const handleCreateClick = () => {
    goToCreate()
  }

  const handleEditClick = (key: BlueprintKey) => {
    goToEdit(`${key.type}:${key.slug}`)
  }

  const handleViewClick = (key: BlueprintKey) => {
    goToDetail(`${key.type}:${key.slug}`)
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
    goToList()
  }

  const handleImport = (data: BlueprintCreate) => {
    createMutation.mutate(data, {
      onSuccess: () => setImportDialogOpen(false),
    })
  }

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <div className="text-sm text-secondary">Loading blueprints...</div>
      </div>
    )
  }

  // Error state
  if (error) {
    return (
      <div className="flex items-center gap-3 rounded-md border border-tertiary bg-danger p-4 text-danger">
        <AlertCircle className="h-5 w-5 flex-shrink-0" />
        <div>
          <div className="font-medium">Failed to load blueprints</div>
          <div className="mt-1 text-sm">
            {error instanceof Error ? error.message : 'An error occurred'}
          </div>
        </div>
      </div>
    )
  }

  // Guard for invalid blueprint URL slugs
  if (
    (viewMode === 'edit' || viewMode === 'detail') &&
    !!selectedSlug &&
    !selectedKey
  ) {
    return (
      <div className="rounded-md border border-tertiary p-4 text-secondary">
        Invalid blueprint URL. Please reopen from the list.
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
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex flex-1 items-center gap-3">
          <div className="relative max-w-md flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-tertiary" />
            <Input
              placeholder="Search blueprints..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="border-tertiary bg-primary pl-10 text-primary placeholder:text-tertiary"
            />
          </div>
          <select
            value={typeFilter}
            onChange={(e) => setTypeFilter(e.target.value)}
            className="h-10 rounded-md border border-tertiary bg-primary px-3 py-2 text-sm text-primary"
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
            className="h-10 rounded-md border border-tertiary bg-primary px-3 py-2 text-sm text-primary"
          >
            <option value="">All Status</option>
            <option value="enabled">Enabled</option>
            <option value="disabled">Disabled</option>
          </select>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={() => setImportDialogOpen(true)}
            className="border-tertiary text-secondary hover:bg-secondary hover:text-primary"
          >
            <Upload className="mr-2 h-4 w-4" />
            Import
          </Button>
          <Button
            onClick={handleCreateClick}
            className="bg-amber-border text-white hover:bg-amber-border-strong"
          >
            <Plus className="mr-2 h-4 w-4" />
            New Blueprint
          </Button>
        </div>
      </div>

      {/* Blueprints Table */}
      <div className="overflow-hidden rounded-md border border-tertiary bg-primary">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead className="border-b border-tertiary bg-secondary">
              <tr>
                <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-secondary">
                  Name
                </th>
                <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-secondary">
                  Slug
                </th>
                <th className="px-5 py-3 text-left text-xs font-medium uppercase tracking-wider text-secondary">
                  Type
                </th>
                <th className="px-5 py-3 text-center text-xs font-medium uppercase tracking-wider text-secondary">
                  Enabled
                </th>
                <th className="px-5 py-3 text-center text-xs font-medium uppercase tracking-wider text-secondary">
                  Filter
                </th>
                <th className="px-5 py-3 text-center text-xs font-medium uppercase tracking-wider text-secondary">
                  Priority
                </th>
                <th className="px-5 py-3 text-center text-xs font-medium uppercase tracking-wider text-secondary">
                  Version
                </th>
                <th className="px-5 py-3 text-right text-xs font-medium uppercase tracking-wider text-secondary">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border-tertiary)]">
              {filteredBlueprints.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-5 py-12 text-center">
                    <div className="text-sm text-tertiary">
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
                    className="cursor-pointer transition-colors hover:bg-secondary"
                  >
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-2.5">
                        <FileJson className="h-4 w-4 flex-shrink-0 text-amber-text-mid" />
                        <div>
                          <span className="text-sm font-medium text-primary">
                            {bp.name}
                          </span>
                          {bp.description && (
                            <div className="mt-0.5 text-xs text-tertiary">
                              {bp.description}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 font-mono text-sm text-secondary">
                      {bp.slug}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5">
                      <span
                        className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium ${getTypeBadgeClasses(bp.type, blueprintTypes, isDarkMode)}`}
                      >
                        {bp.type}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-center">
                      {bp.enabled ? (
                        <CheckCircle className="mx-auto h-4 w-4 text-success" />
                      ) : (
                        <XCircle className="mx-auto h-4 w-4 text-tertiary" />
                      )}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-center">
                      {renderFilterCell(bp.filter, isDarkMode) || (
                        <span className="text-xs text-tertiary">&mdash;</span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-center text-sm text-primary">
                      {bp.priority}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5 text-center font-mono text-sm text-secondary">
                      v{bp.version}
                    </td>
                    <td className="whitespace-nowrap px-5 py-3.5">
                      <div className="flex items-center justify-end gap-1">
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleEditClick({
                              type: bp.type,
                              slug: bp.slug,
                            })
                          }}
                          className="rounded-sm p-1.5 text-tertiary transition-colors hover:bg-secondary hover:text-primary"
                          title="Edit"
                        >
                          <Edit2 className="h-4 w-4" />
                        </button>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            handleDelete({ type: bp.type, slug: bp.slug })
                          }}
                          disabled={deleteMutation.isPending}
                          className="rounded-sm p-1.5 text-tertiary transition-colors hover:bg-danger hover:text-danger"
                          title="Delete"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Import Dialog */}
      <ImportBlueprintDialog
        isOpen={importDialogOpen}
        onClose={() => {
          setImportDialogOpen(false)
          createMutation.reset()
        }}
        onImport={handleImport}
        blueprintTypes={blueprintTypes}
        isDarkMode={isDarkMode}
        isLoading={createMutation.isPending}
        apiError={importDialogOpen ? createMutation.error : null}
      />
    </div>
  )
}
