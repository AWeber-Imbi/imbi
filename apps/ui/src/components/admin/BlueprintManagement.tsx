/* eslint-disable react-refresh/only-export-components */
import React from 'react'
import { useState, useMemo } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Plus,
  Search,
  FileJson,
  AlertCircle,
  CheckCircle,
  XCircle,
  Upload,
  Filter,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { AdminTable } from '@/components/ui/admin-table'
import { LabelChip } from '@/components/ui/label-chip'
import { LABEL_SWATCHES, swatchForType } from '@/lib/chip-colors'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { BlueprintForm } from './blueprints/BlueprintForm'
import { BlueprintDetail } from './blueprints/BlueprintDetail'
import { ImportBlueprintDialog } from './blueprints/ImportBlueprintDialog'
import { useAdminNav } from '@/hooks/useAdminNav'
import {
  listBlueprints,
  deleteBlueprint,
  createBlueprint,
  updateBlueprint,
} from '@/api/endpoints'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { Blueprint, BlueprintCreate } from '@/types'

interface BlueprintKey {
  type: string
  slug: string
}

/** Return the path type used in API URLs and compound keys. */
export function blueprintPathType(bp: Blueprint): string {
  return bp.kind === 'relationship' ? 'relationship' : bp.type || 'unknown'
}

/** Label shown in the type badge. */
export function blueprintTypeLabel(bp: Blueprint): string {
  if (bp.kind === 'relationship') {
    return `${bp.source ?? '?'} → ${bp.target ?? '?'} (${bp.edge ?? '?'})`
  }
  return bp.type || 'unknown'
}

/** Pick a label palette hex for a blueprint type. Relationship is pinned to Honey. */
export function getTypeSwatch(type: string, allTypes: string[]): string {
  if (type === 'relationship') {
    return (
      LABEL_SWATCHES.find((s) => s.name === 'Honey')?.hex ??
      LABEL_SWATCHES[2].hex
    )
  }
  return swatchForType(type, allTypes)
}

function renderFilterCell(filter: string | null | undefined): React.ReactNode {
  const f = parseFilterFromBlueprint(filter)
  if (!f) return null
  const tooltipLines = [
    f.project_type?.length ? `Project Types: ${f.project_type.join(', ')}` : '',
    f.environment?.length ? `Environments: ${f.environment.join(', ')}` : '',
  ].filter(Boolean)
  return (
    <TooltipProvider delayDuration={200}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span>
            <Filter className={'mx-auto h-4 w-4 text-warning'} />
          </span>
        </TooltipTrigger>
        <TooltipContent>
          {tooltipLines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  )
}

export function BlueprintManagement() {
  const queryClient = useQueryClient()
  const {
    viewMode,
    slug: selectedSlug,
    goToList,
    goToCreate,
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

  // Known node types for blueprint targets
  const blueprintTypes = [
    'Environment',
    'Organization',
    'Project',
    'ProjectType',
    'Team',
    'ThirdPartyService',
  ]

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
    if (typeFilter === 'relationship') {
      if (bp.kind !== 'relationship') return false
    } else if (typeFilter && bp.type !== typeFilter) return false
    if (enabledFilter === 'enabled' && !bp.enabled) return false
    if (enabledFilter === 'disabled' && bp.enabled) return false
    return true
  })

  const handleCreateClick = () => {
    goToCreate()
  }

  const handleEditClick = (key: BlueprintKey) => {
    goToEdit(`${key.type}:${key.slug}`)
  }

  const handleViewClick = (key: BlueprintKey) => {
    goToEdit(`${key.type}:${key.slug}`)
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
            <option value="relationship">Relationship</option>
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
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Plus className="mr-2 h-4 w-4" />
            New Blueprint
          </Button>
        </div>
      </div>

      <AdminTable<Blueprint>
        columns={[
          {
            key: 'name',
            header: 'Name',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (bp) => (
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
            ),
          },
          {
            key: 'slug',
            header: 'Slug',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (bp) => (
              <span className="whitespace-nowrap font-mono text-sm text-secondary">
                {bp.slug}
              </span>
            ),
          },
          {
            key: 'type',
            header: 'Type',
            headerAlign: 'left',
            cellAlign: 'left',
            render: (bp) => (
              <LabelChip
                hex={getTypeSwatch(blueprintPathType(bp), blueprintTypes)}
              >
                {blueprintTypeLabel(bp)}
              </LabelChip>
            ),
          },
          {
            key: 'enabled',
            header: 'Enabled',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (bp) =>
              bp.enabled ? (
                <CheckCircle className="mx-auto h-4 w-4 text-success" />
              ) : (
                <XCircle className="mx-auto h-4 w-4 text-tertiary" />
              ),
          },
          {
            key: 'filter',
            header: 'Filter',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (bp) =>
              renderFilterCell(bp.filter) || (
                <span className="text-xs text-tertiary">&mdash;</span>
              ),
          },
          {
            key: 'priority',
            header: 'Priority',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (bp) => (
              <span className="whitespace-nowrap text-sm text-primary">
                {bp.priority}
              </span>
            ),
          },
          {
            key: 'version',
            header: 'Version',
            headerAlign: 'center',
            cellAlign: 'center',
            render: (bp) => (
              <span className="whitespace-nowrap font-mono text-sm text-secondary">
                v{bp.version}
              </span>
            ),
          },
        ]}
        rows={filteredBlueprints}
        getRowKey={(bp) => `${blueprintPathType(bp)}/${bp.slug}`}
        getDeleteLabel={(bp) => bp.name}
        onRowClick={(bp) =>
          handleViewClick({ type: blueprintPathType(bp), slug: bp.slug })
        }
        onDelete={(bp) =>
          deleteMutation.mutate({ type: blueprintPathType(bp), slug: bp.slug })
        }
        isDeleting={deleteMutation.isPending}
        emptyMessage={
          searchQuery || typeFilter || enabledFilter
            ? 'No blueprints match your filters'
            : 'No blueprints created yet'
        }
      />

      {/* Import Dialog */}
      <ImportBlueprintDialog
        isOpen={importDialogOpen}
        onClose={() => {
          setImportDialogOpen(false)
          createMutation.reset()
        }}
        onImport={handleImport}
        blueprintTypes={blueprintTypes}
        isLoading={createMutation.isPending}
        apiError={importDialogOpen ? createMutation.error : null}
      />
    </div>
  )
}
