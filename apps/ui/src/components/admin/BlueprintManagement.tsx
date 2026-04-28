/* eslint-disable react-refresh/only-export-components */
import React from 'react'
import { useMemo, useState } from 'react'

import { CheckCircle, FileJson, Filter, Upload, XCircle } from 'lucide-react'

import {
  createBlueprint,
  deleteBlueprint,
  listBlueprints,
  updateBlueprint,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import { LabelChip } from '@/components/ui/label-chip'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { LABEL_SWATCHES, swatchForType } from '@/lib/chip-colors'
import { buildDiffPatch } from '@/lib/json-patch'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { Blueprint, BlueprintCreate, PatchOperation } from '@/types'

import { AdminSection } from './AdminSection'
import { BlueprintDetail } from './blueprints/BlueprintDetail'
import { BlueprintForm } from './blueprints/BlueprintForm'
import { ImportBlueprintDialog } from './blueprints/ImportBlueprintDialog'

interface BlueprintKey {
  slug: string
  type: string
}

export function BlueprintManagement() {
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedSlug,
    viewMode,
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
      slug: selectedSlug.substring(colonIdx + 1),
      type: selectedSlug.substring(0, colonIdx),
    }
  }, [selectedSlug])

  // Known node types for blueprint targets
  const blueprintTypes = [
    'Environment',
    'Organization',
    'Project',
    'ProjectType',
    'Team',
    'ThirdPartyService',
  ]

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: blueprints,
    updateMutation,
  } = useAdminCrud<
    Blueprint,
    BlueprintCreate,
    { operations: PatchOperation[]; slug: string; type: string },
    BlueprintKey
  >({
    createFn: (blueprint) => createBlueprint(blueprint),
    deleteErrorLabel: 'blueprint',
    deleteFn: ({ slug, type }) => deleteBlueprint(type, slug),
    // The backend auto-refreshes its OpenAPI schema cache on blueprint CRUD;
    // invalidate frontend caches derived from it.
    extraInvalidateKeys: [
      ['blueprint'],
      ['openapi-spec'],
      ['teamSchema'],
      ['environmentSchema'],
      ['projectTypeSchema'],
    ],
    listFn: (signal) => listBlueprints(undefined, signal),
    onMutationSuccess: goToList,
    queryKey: ['blueprints'],
    updateFn: ({ operations, slug, type }) =>
      updateBlueprint(type, slug, operations),
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
      const existing = blueprints.find(
        (bp) =>
          blueprintPathType(bp) === selectedKey.type &&
          bp.slug === selectedKey.slug,
      )
      if (!existing) return
      const operations = buildDiffPatch(
        existing as unknown as Record<string, unknown>,
        data as unknown as Record<string, unknown>,
        { fields: Object.keys(data) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({
        operations,
        slug: selectedKey.slug,
        type: selectedKey.type,
      })
    }
  }

  const handleCancel = () => {
    // Clear any prior create/import/update error so switching back to the
    // list and then re-entering any flow starts clean.
    createMutation.reset()
    updateMutation.reset()
    goToList()
  }

  const handleCreate = () => {
    // Drop any error from a previous failed import/edit before entering the form.
    createMutation.reset()
    updateMutation.reset()
    goToCreate()
  }

  const handleOpenImport = () => {
    // Drop any error from a previous failed create/edit before opening the dialog.
    createMutation.reset()
    updateMutation.reset()
    setImportDialogOpen(true)
  }

  const handleImport = (data: BlueprintCreate) => {
    createMutation.mutate(data, {
      onSuccess: () => setImportDialogOpen(false),
    })
  }

  // Guard for invalid blueprint URL slugs
  if (
    !isLoading &&
    !error &&
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

  if (viewMode === 'create' || viewMode === 'edit') {
    const isCreate = viewMode === 'create'
    return (
      <BlueprintForm
        blueprintKey={selectedKey}
        blueprintTypes={blueprintTypes}
        error={isCreate ? createMutation.error : updateMutation.error}
        isLoading={
          isCreate ? createMutation.isPending : updateMutation.isPending
        }
        key={selectedKey ? `${selectedKey.type}/${selectedKey.slug}` : 'create'}
        onCancel={handleCancel}
        onSave={handleSave}
      />
    )
  }

  if (viewMode === 'detail' && selectedKey) {
    return (
      <BlueprintDetail
        blueprintKey={selectedKey}
        blueprintTypes={blueprintTypes}
        key={`${selectedKey.type}/${selectedKey.slug}`}
        onBack={handleCancel}
        onEdit={() => handleEditClick(selectedKey)}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Blueprint"
      error={error}
      errorTitle="Failed to load blueprints"
      headerActions={
        <Button
          className="border-tertiary text-secondary hover:bg-secondary hover:text-primary"
          onClick={handleOpenImport}
          variant="outline"
        >
          <Upload className="mr-2 h-4 w-4" />
          Import
        </Button>
      }
      headerExtras={
        <>
          <select
            aria-label="Filter blueprints by type"
            className="h-10 rounded-md border border-tertiary bg-primary px-3 py-2 text-sm text-primary"
            onChange={(e) => setTypeFilter(e.target.value)}
            value={typeFilter}
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
            aria-label="Filter blueprints by status"
            className="h-10 rounded-md border border-tertiary bg-primary px-3 py-2 text-sm text-primary"
            onChange={(e) => setEnabledFilter(e.target.value)}
            value={enabledFilter}
          >
            <option value="">All Status</option>
            <option value="enabled">Enabled</option>
            <option value="disabled">Disabled</option>
          </select>
        </>
      }
      isLoading={isLoading}
      loadingLabel="Loading blueprints..."
      onCreate={handleCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search blueprints..."
    >
      <AdminTable<Blueprint>
        columns={[
          {
            cellAlign: 'left',
            header: 'Name',
            headerAlign: 'left',
            key: 'name',
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
            cellAlign: 'left',
            header: 'Slug',
            headerAlign: 'left',
            key: 'slug',
            render: (bp) => (
              <span className="whitespace-nowrap font-mono text-sm text-secondary">
                {bp.slug}
              </span>
            ),
          },
          {
            cellAlign: 'left',
            header: 'Type',
            headerAlign: 'left',
            key: 'type',
            render: (bp) => (
              <LabelChip
                hex={getTypeSwatch(blueprintPathType(bp), blueprintTypes)}
              >
                {blueprintTypeLabel(bp)}
              </LabelChip>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Enabled',
            headerAlign: 'center',
            key: 'enabled',
            render: (bp) =>
              bp.enabled ? (
                <CheckCircle className="mx-auto h-4 w-4 text-success" />
              ) : (
                <XCircle className="mx-auto h-4 w-4 text-tertiary" />
              ),
          },
          {
            cellAlign: 'center',
            header: 'Filter',
            headerAlign: 'center',
            key: 'filter',
            render: (bp) =>
              renderFilterCell(bp.filter) || (
                <span className="text-xs text-tertiary">&mdash;</span>
              ),
          },
          {
            cellAlign: 'center',
            header: 'Priority',
            headerAlign: 'center',
            key: 'priority',
            render: (bp) => (
              <span className="whitespace-nowrap text-sm text-primary">
                {bp.priority}
              </span>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Version',
            headerAlign: 'center',
            key: 'version',
            render: (bp) => (
              <span className="whitespace-nowrap font-mono text-sm text-secondary">
                v{bp.version}
              </span>
            ),
          },
        ]}
        emptyMessage={
          searchQuery || typeFilter || enabledFilter
            ? 'No blueprints match your filters'
            : 'No blueprints created yet'
        }
        getDeleteLabel={(bp) => bp.name}
        getRowKey={(bp) => `${blueprintPathType(bp)}/${bp.slug}`}
        isDeleting={deleteMutation.isPending}
        onDelete={(bp) => {
          if (!bp.slug) return
          deleteMutation.mutate({
            slug: bp.slug,
            type: blueprintPathType(bp),
          })
        }}
        onRowClick={(bp) => {
          if (!bp.slug) return
          handleViewClick({
            slug: bp.slug,
            type: blueprintPathType(bp),
          })
        }}
        rows={filteredBlueprints}
      />

      {/* Import Dialog */}
      <ImportBlueprintDialog
        apiError={importDialogOpen ? createMutation.error : null}
        blueprintTypes={blueprintTypes}
        isLoading={createMutation.isPending}
        isOpen={importDialogOpen}
        onClose={() => {
          setImportDialogOpen(false)
          createMutation.reset()
        }}
        onImport={handleImport}
      />
    </AdminSection>
  )
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

function renderFilterCell(filter: null | string | undefined): React.ReactNode {
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
            <Filter className="mx-auto h-4 w-4 text-warning" />
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
