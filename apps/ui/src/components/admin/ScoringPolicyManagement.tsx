import { useMemo, useState } from 'react'

import { useMutation } from '@tanstack/react-query'
import { CheckCircle, RefreshCw, XCircle } from 'lucide-react'

import {
  createScoringPolicy,
  deleteScoringPolicy,
  listScoringPolicies,
  rescoreAll,
  updateScoringPolicy,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { buildDiffPatch } from '@/lib/json-patch'
import type {
  PatchOperation,
  ScoringPolicy,
  ScoringPolicyCreate,
} from '@/types'

import { AdminSection } from './AdminSection'
import { ScoringPolicyForm } from './scoring-policies/ScoringPolicyForm'

export function ScoringPolicyManagement() {
  const {
    goToCreate,
    goToEdit,
    goToList,
    slug: selectedSlug,
    viewMode,
  } = useAdminNav()
  const [searchQuery, setSearchQuery] = useState('')
  const [enabledFilter, setEnabledFilter] = useState('')
  const [rescoreResult, setRescoreResult] = useState<null | number>(null)

  const rescoreMutation = useMutation({
    mutationFn: rescoreAll,
    onSuccess: (data) => {
      setRescoreResult(data.enqueued)
      setTimeout(() => setRescoreResult(null), 4000)
    },
  })

  const {
    createMutation,
    deleteMutation,
    error,
    isLoading,
    items: policies,
    updateMutation,
  } = useAdminCrud<
    ScoringPolicy,
    ScoringPolicyCreate,
    { operations: PatchOperation[]; slug: string },
    string
  >({
    createFn: createScoringPolicy,
    deleteErrorLabel: 'scoring policy',
    deleteFn: deleteScoringPolicy,
    listFn: listScoringPolicies,
    onMutationSuccess: goToList,
    queryKey: ['scoring-policies'],
    updateFn: ({ operations, slug }) => updateScoringPolicy(slug, operations),
  })

  const selectedPolicy = useMemo(
    () => policies.find((p) => p.slug === selectedSlug) ?? null,
    [policies, selectedSlug],
  )

  const filteredPolicies = policies.filter((p) => {
    if (searchQuery) {
      const q = searchQuery.toLowerCase()
      if (
        !p.name.toLowerCase().includes(q) &&
        !p.slug.toLowerCase().includes(q) &&
        !(p.description?.toLowerCase().includes(q) ?? false) &&
        !p.attribute_name.toLowerCase().includes(q)
      )
        return false
    }
    if (enabledFilter === 'enabled' && !p.enabled) return false
    if (enabledFilter === 'disabled' && p.enabled) return false
    return true
  })

  const handleSave = (data: ScoringPolicyCreate) => {
    if (viewMode === 'create') {
      createMutation.mutate(data)
    } else if (selectedSlug && selectedPolicy) {
      const operations = buildDiffPatch(
        selectedPolicy as unknown as Record<string, unknown>,
        data as unknown as Record<string, unknown>,
        { fields: Object.keys(data) },
      )
      if (operations.length === 0) {
        goToList()
        return
      }
      updateMutation.mutate({ operations, slug: selectedSlug })
    }
  }

  const handleCancel = () => {
    createMutation.reset()
    updateMutation.reset()
    goToList()
  }

  if (viewMode === 'create' || viewMode === 'edit') {
    return (
      <ScoringPolicyForm
        error={createMutation.error ?? updateMutation.error}
        isLoading={createMutation.isPending || updateMutation.isPending}
        onCancel={handleCancel}
        onSave={handleSave}
        policy={viewMode === 'edit' ? selectedPolicy : null}
      />
    )
  }

  return (
    <AdminSection
      createLabel="New Policy"
      error={error}
      errorTitle="Failed to load scoring policies"
      headerActions={
        <Button
          disabled={rescoreMutation.isPending}
          onClick={() => rescoreMutation.mutate()}
          variant="outline"
        >
          <RefreshCw
            className={`mr-2 h-4 w-4 ${rescoreMutation.isPending ? 'animate-spin' : ''}`}
          />
          {rescoreResult !== null
            ? `Enqueued ${rescoreResult}`
            : 'Recompute Scores'}
        </Button>
      }
      headerExtras={
        <select
          className="rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground"
          onChange={(e) => setEnabledFilter(e.target.value)}
          value={enabledFilter}
        >
          <option value="">All</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
        </select>
      }
      isLoading={isLoading}
      loadingLabel="Loading scoring policies..."
      onCreate={goToCreate}
      onSearchChange={setSearchQuery}
      search={searchQuery}
      searchPlaceholder="Search policies..."
    >
      <AdminTable<ScoringPolicy>
        columns={[
          {
            cellAlign: 'left',
            header: 'Policy',
            headerAlign: 'left',
            key: 'name',
            render: (p) => (
              <div>
                <div className="font-medium text-primary">{p.name}</div>
                {p.description && (
                  <div className="mt-0.5 text-xs text-tertiary">
                    {p.description}
                  </div>
                )}
              </div>
            ),
          },
          {
            cellAlign: 'left',
            header: 'Attribute',
            headerAlign: 'left',
            key: 'attribute',
            render: (p) => (
              <code className="rounded bg-secondary px-1.5 py-0.5 text-xs text-primary">
                {p.attribute_name}
              </code>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Weight',
            headerAlign: 'center',
            key: 'weight',
            render: (p) => <span className="text-secondary">{p.weight}</span>,
          },
          {
            cellAlign: 'center',
            header: 'Priority',
            headerAlign: 'center',
            key: 'priority',
            render: (p) => <span className="text-secondary">{p.priority}</span>,
          },
          {
            cellAlign: 'left',
            header: 'Targets',
            headerAlign: 'left',
            key: 'targets',
            render: (p) => (
              <span className="text-xs text-tertiary">
                {(p.targets ?? []).length === 0
                  ? 'All types'
                  : (p.targets ?? []).join(', ')}
              </span>
            ),
          },
          {
            cellAlign: 'center',
            header: 'Enabled',
            headerAlign: 'center',
            key: 'enabled',
            render: (p) =>
              p.enabled ? (
                <CheckCircle className="mx-auto h-4 w-4 text-success" />
              ) : (
                <XCircle className="mx-auto h-4 w-4 text-tertiary" />
              ),
          },
        ]}
        emptyMessage={
          searchQuery || enabledFilter
            ? 'No policies match your filters.'
            : 'No scoring policies defined yet.'
        }
        getDeleteLabel={(p) => p.name}
        getRowKey={(p) => p.slug}
        isDeleting={deleteMutation.isPending}
        onDelete={(p) => deleteMutation.mutate(p.slug)}
        onRowClick={(p) => goToEdit(p.slug)}
        rows={filteredPolicies}
      />
    </AdminSection>
  )
}
