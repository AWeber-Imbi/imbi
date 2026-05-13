import { useMemo, useState } from 'react'

import { useMutation } from '@tanstack/react-query'
import {
  Check,
  CheckCircle,
  Copy,
  RefreshCw,
  Upload,
  XCircle,
} from 'lucide-react'

import {
  createScoringPolicy,
  deleteScoringPolicy,
  listScoringPolicies,
  rescoreAll,
  updateScoringPolicy,
} from '@/api/endpoints'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { useAdminCrud } from '@/hooks/useAdminCrud'
import { useAdminNav } from '@/hooks/useAdminNav'
import { buildDiffPatch } from '@/lib/json-patch'
import type {
  AttributeScoringPolicy,
  PatchOperation,
  ScoringPolicy,
  ScoringPolicyCategory,
  ScoringPolicyCreate,
} from '@/types'

import { AdminSection } from './AdminSection'
import { ImportScoringPolicyDialog } from './scoring-policies/ImportScoringPolicyDialog'
import { ScoringPolicyForm } from './scoring-policies/ScoringPolicyForm'

const CATEGORY_LABELS: Record<ScoringPolicyCategory, string> = {
  age: 'Age',
  attribute: 'Attribute',
  link_presence: 'Link Presence',
  presence: 'Presence',
}

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
  const [importDialogOpen, setImportDialogOpen] = useState(false)
  const [copiedSlug, setCopiedSlug] = useState<null | string>(null)

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
      const subjectKey = policySubjectKey(p).toLowerCase()
      if (
        !p.name.toLowerCase().includes(q) &&
        !p.slug.toLowerCase().includes(q) &&
        !(p.description?.toLowerCase().includes(q) ?? false) &&
        !subjectKey.includes(q)
      )
        return false
    }
    if (enabledFilter === 'enabled' && !p.enabled) return false
    if (enabledFilter === 'disabled' && p.enabled) return false
    return true
  })

  const handleCopy = (policy: ScoringPolicy) => {
    const exportObj = policyToExportPayload(policy)
    if (!navigator.clipboard?.writeText) return
    navigator.clipboard
      .writeText(JSON.stringify(exportObj, null, 2))
      .then(() => {
        setCopiedSlug(policy.slug)
        setTimeout(() => setCopiedSlug(null), 2000)
      })
      .catch(() => {
        setCopiedSlug(null)
      })
  }

  const handleImport = (data: ScoringPolicyCreate) => {
    createMutation.mutate(data, {
      onSuccess: () => setImportDialogOpen(false),
    })
  }

  const handleOpenImport = () => {
    createMutation.reset()
    setImportDialogOpen(true)
  }

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
    <>
      <AdminSection
        createLabel="New Policy"
        error={error}
        errorTitle="Failed to load scoring policies"
        headerActions={
          <>
            <Button onClick={handleOpenImport} variant="outline">
              <Upload className="mr-2 size-4" />
              Import
            </Button>
            <Button
              disabled={rescoreMutation.isPending}
              onClick={() => rescoreMutation.mutate()}
              variant="outline"
            >
              <RefreshCw
                className={`mr-2 size-4 ${rescoreMutation.isPending ? 'animate-spin' : ''}`}
              />
              {rescoreResult !== null
                ? `Enqueued ${rescoreResult}`
                : 'Recompute Scores'}
            </Button>
          </>
        }
        headerExtras={
          <select
            className="border-input bg-background text-foreground rounded-lg border px-3 py-2 text-sm"
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
          actions={(p) => (
            <TooltipProvider delayDuration={200}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    aria-label={`Copy ${p.name}`}
                    onClick={(e) => {
                      e.stopPropagation()
                      handleCopy(p)
                    }}
                    size="sm"
                    variant="ghost"
                  >
                    {copiedSlug === p.slug ? (
                      <Check className="size-4 text-green-500" />
                    ) : (
                      <Copy className="text-secondary size-4" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p>Copy Definition</p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          )}
          columns={[
            {
              cellAlign: 'left',
              header: 'Policy',
              headerAlign: 'left',
              key: 'name',
              render: (p) => (
                <div>
                  <div className="text-primary font-medium">{p.name}</div>
                  {p.description && (
                    <div className="text-tertiary mt-0.5 text-xs">
                      {p.description}
                    </div>
                  )}
                </div>
              ),
            },
            {
              cellAlign: 'left',
              header: 'Category',
              headerAlign: 'left',
              key: 'category',
              render: (p) => (
                <span className="bg-secondary text-secondary rounded px-1.5 py-0.5 text-xs">
                  {CATEGORY_LABELS[p.category]}
                </span>
              ),
            },
            {
              cellAlign: 'left',
              header: 'Subject',
              headerAlign: 'left',
              key: 'subject',
              render: (p) => (
                <code className="bg-secondary text-primary rounded px-1.5 py-0.5 text-xs">
                  {policySubjectKey(p)}
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
              render: (p) => (
                <span className="text-secondary">{p.priority}</span>
              ),
            },
            {
              cellAlign: 'left',
              header: 'Targets',
              headerAlign: 'left',
              key: 'targets',
              render: (p) => (
                <span className="text-tertiary text-xs">
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
                  <CheckCircle className="text-success mx-auto size-4" />
                ) : (
                  <XCircle className="text-tertiary mx-auto size-4" />
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

      <ImportScoringPolicyDialog
        apiError={createMutation.error}
        isLoading={createMutation.isPending}
        isOpen={importDialogOpen}
        onClose={() => setImportDialogOpen(false)}
        onImport={handleImport}
      />
    </>
  )
}

function attributeExport(
  policy: AttributeScoringPolicy,
): Record<string, unknown> {
  const out: Record<string, unknown> = { attribute_name: policy.attribute_name }
  if (policy.value_score_map) out.value_score_map = policy.value_score_map
  if (policy.range_score_map) out.range_score_map = policy.range_score_map
  return out
}

// fallow-ignore-next-line complexity
function categorySpecificExport(
  policy: ScoringPolicy,
): Record<string, unknown> {
  switch (policy.category) {
    case 'age':
      return {
        age_score_map: policy.age_score_map,
        attribute_name: policy.attribute_name,
      }
    case 'attribute':
      return attributeExport(policy)
    case 'link_presence':
      return presenceExport({
        missing_score: policy.missing_score,
        present_score: policy.present_score,
        subject: { link_slug: policy.link_slug },
      })
    case 'presence':
      return presenceExport({
        missing_score: policy.missing_score,
        present_score: policy.present_score,
        subject: { attribute_name: policy.attribute_name },
      })
  }
}

function policySubjectKey(policy: ScoringPolicy): string {
  return policy.category === 'link_presence'
    ? policy.link_slug
    : policy.attribute_name
}

function policyToExportPayload(policy: ScoringPolicy): Record<string, unknown> {
  const base: Record<string, unknown> = {
    category: policy.category,
    enabled: policy.enabled,
    name: policy.name,
    priority: policy.priority,
    slug: policy.slug,
    targets: policy.targets ?? [],
    weight: policy.weight,
  }
  if (policy.description) base.description = policy.description
  return { ...base, ...categorySpecificExport(policy) }
}

function presenceExport(args: {
  missing_score?: null | number
  present_score?: null | number
  subject: Record<string, unknown>
}): Record<string, unknown> {
  const out: Record<string, unknown> = { ...args.subject }
  if (args.present_score != null) out.present_score = args.present_score
  if (args.missing_score != null) out.missing_score = args.missing_score
  return out
}
