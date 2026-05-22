/* eslint-disable react-refresh/only-export-components */
import React from 'react'
import { useMemo, useState } from 'react'

import {
  Check,
  CheckCircle,
  Copy,
  FileJson,
  Filter,
  Upload,
  XCircle,
} from 'lucide-react'

import {
  createBlueprint,
  deleteBlueprint,
  listBlueprints,
  updateBlueprint,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import { LabelChip } from '@/components/ui/label-chip'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { useClipboard } from '@/hooks/useClipboard'
import { buildDiffPatch } from '@/lib/json-patch'
import { parseFilterFromBlueprint } from '@/lib/utils'
import type { Blueprint, BlueprintCreate, PatchOperation } from '@/types'

import { AdminSection } from './AdminSection'
import { BlueprintDetail } from './blueprints/BlueprintDetail'
import { BlueprintForm } from './blueprints/BlueprintForm'
import { ImportBlueprintDialog } from './blueprints/ImportBlueprintDialog'
import { getTypeSwatch } from './blueprints/typeSwatch'

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
  // 'all' acts as the unfiltered sentinel; Radix Select disallows '' values.
  const [typeFilter, setTypeFilter] = useState<string>('all')
  const [enabledFilter, setEnabledFilter] = useState<string>('all')
  const [importDialogOpen, setImportDialogOpen] = useState(false)
  const { copied: copiedKey, copy } = useClipboard()
  const [copyError, setCopyError] = useState<null | string>(null)

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
    } else if (typeFilter !== 'all' && bp.type !== typeFilter) return false
    if (enabledFilter === 'enabled' && !bp.enabled) return false
    if (enabledFilter === 'disabled' && bp.enabled) return false
    return true
  })

  const handleCopyBlueprint = (bp: Blueprint) => {
    let schemaObj: Record<string, unknown>
    try {
      schemaObj =
        typeof bp.json_schema === 'string'
          ? JSON.parse(bp.json_schema)
          : bp.json_schema
    } catch {
      setCopyError(`Failed to copy "${bp.name}": invalid JSON schema`)
      return
    }
    const parsedFilter = parseFilterFromBlueprint(bp.filter)
    const exportObj: Record<string, unknown> = {
      kind: bp.kind || 'node',
      name: bp.name,
      slug: bp.slug,
      ...(bp.kind === 'relationship'
        ? {
            edge: bp.edge ?? '',
            source: bp.source ?? '',
            target: bp.target ?? '',
          }
        : { type: bp.type }),
      ...(bp.description ? { description: bp.description } : {}),
      enabled: bp.enabled,
      priority: bp.priority,
      ...(parsedFilter &&
      (parsedFilter.project_type?.length > 0 ||
        parsedFilter.environment?.length > 0)
        ? { filter: parsedFilter }
        : {}),
      json_schema: schemaObj,
    }
    const rowKey = `${blueprintPathType(bp)}/${bp.slug}`
    void copy(JSON.stringify(exportObj, null, 2), rowKey).then((ok) => {
      if (ok) setCopyError(null)
      else setCopyError(`Failed to copy "${bp.name}" to clipboard`)
    })
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
      <div className="border-tertiary text-secondary rounded-md border p-4">
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
          <Upload className="mr-2 size-4" />
          Import
        </Button>
      }
      headerExtras={
        <>
          <Select onValueChange={setTypeFilter} value={typeFilter}>
            <SelectTrigger
              aria-label="Filter blueprints by type"
              className="w-44"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              {blueprintTypes.map((t) => (
                <SelectItem key={t} value={t}>
                  {t}
                </SelectItem>
              ))}
              <SelectItem value="relationship">Relationship</SelectItem>
            </SelectContent>
          </Select>
          <Select onValueChange={setEnabledFilter} value={enabledFilter}>
            <SelectTrigger
              aria-label="Filter blueprints by status"
              className="w-36"
            >
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Status</SelectItem>
              <SelectItem value="enabled">Enabled</SelectItem>
              <SelectItem value="disabled">Disabled</SelectItem>
            </SelectContent>
          </Select>
        </>
      }
      isLoading={isLoading}
      loadingLabel="Loading blueprints..."
      onCreate={handleCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search blueprints..."
    >
      {copyError && <ErrorBanner message={copyError} title="Copy failed" />}
      <AdminTable<Blueprint>
        actions={(bp) => {
          const rowKey = `${blueprintPathType(bp)}/${bp.slug}`
          const isCopied = copiedKey === rowKey
          return (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    aria-label={`Copy ${bp.name} as JSON`}
                    className="text-secondary hover:bg-secondary hover:text-primary"
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCopyBlueprint(bp)
                    }}
                    size="sm"
                    variant="ghost"
                  >
                    {isCopied ? (
                      <Check className="text-success size-4" />
                    ) : (
                      <Copy className="size-4" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>{isCopied ? 'Copied!' : 'Copy Definition'}</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )
        }}
        columns={[
          {
            cellAlign: 'left',
            header: 'Name',
            headerAlign: 'left',
            key: 'name',
            render: (bp) => (
              <div className="flex items-center gap-2.5">
                <FileJson className="text-amber-text-mid size-4 shrink-0" />
                <div>
                  <span className="text-primary text-sm font-medium">
                    {bp.name}
                  </span>
                  {bp.description && (
                    <div className="text-tertiary mt-0.5 text-xs">
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
              <span className="text-secondary font-mono text-sm whitespace-nowrap">
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
                <CheckCircle className="text-success mx-auto size-4" />
              ) : (
                <XCircle className="text-tertiary mx-auto size-4" />
              ),
          },
          {
            cellAlign: 'center',
            header: 'Filter',
            headerAlign: 'center',
            key: 'filter',
            render: (bp) =>
              renderFilterCell(bp.filter) || (
                <span className="text-tertiary text-xs">&mdash;</span>
              ),
          },
          {
            cellAlign: 'center',
            header: 'Priority',
            headerAlign: 'center',
            key: 'priority',
            render: (bp) => (
              <span className="text-primary text-sm whitespace-nowrap">
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
              <span className="text-secondary font-mono text-sm whitespace-nowrap">
                v{bp.version}
              </span>
            ),
          },
        ]}
        emptyMessage={
          searchQuery || typeFilter !== 'all' || enabledFilter !== 'all'
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
function blueprintPathType(bp: Blueprint): string {
  return bp.kind === 'relationship' ? 'relationship' : bp.type || 'unknown'
}

/** Label shown in the type badge. */
function blueprintTypeLabel(bp: Blueprint): string {
  if (bp.kind === 'relationship') {
    return `${bp.source ?? '?'} → ${bp.target ?? '?'} (${bp.edge ?? '?'})`
  }
  return bp.type || 'unknown'
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
            <Filter className="text-warning mx-auto size-4" />
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
