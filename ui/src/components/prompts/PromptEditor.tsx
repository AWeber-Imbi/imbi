import { type ReactNode, useMemo, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpCircle,
  Download,
  Tag,
  Trash2,
  TriangleAlert,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import { ApiError } from '@/api/client'
import {
  deletePrompt,
  deletePromptLabel,
  getPrompt,
  listPromptVersions,
  setPromptDefaultLabel,
  setPromptLabel,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { Sk } from '@/components/ui/skeleton'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { Prompt, PromptEvalSummary, PromptVersion } from '@/types'

import { PromoteDialog, type PromoteValues } from './PromoteDialog'
import { VersionWorkspace } from './VersionWorkspace'

const HAIRLINE = { borderWidth: '0.5px' }

interface PromptEditorProps {
  className?: string
  /** Rendered instead of the editor when the prompt does not exist. */
  emptyState?: ReactNode
  namespace: string
  /** Called after the prompt is deleted. */
  onDeleted?: () => void
  slug: string
}

/**
 * One prompt from the CMS: labels, versions, and the version editor.
 * It needs no router and no tree, so any page can embed it.
 */
export function PromptEditor({
  className,
  emptyState,
  namespace,
  onDeleted,
  slug,
}: PromptEditorProps) {
  const promptQuery = useQuery({
    queryFn: ({ signal }) => getPrompt(namespace, slug, signal),
    queryKey: queryKeys.prompt(namespace, slug),
    // A missing prompt is an answer, not a failure: show the empty state
    // at once instead of retrying.
    retry: (failures, error) =>
      !(error instanceof ApiError && error.status === 404) && failures < 1,
  })
  // ``isPending``, not ``isLoading``: a retry paused while the window is
  // not focused is pending but not loading, and must not render nothing.
  if (promptQuery.isPending) return <Sk className="h-40 w-full" />
  if (
    promptQuery.error instanceof ApiError &&
    promptQuery.error.status === 404
  ) {
    return <>{emptyState ?? null}</>
  }
  if (promptQuery.error != null) {
    return (
      <ErrorBanner error={promptQuery.error} title="Failed to load prompt" />
    )
  }
  if (!promptQuery.data) return null
  return (
    <PromptView
      className={className}
      key={promptQuery.data.id}
      onDeleted={onDeleted}
      prompt={promptQuery.data}
    />
  )
}

function downloadJson(filename: string, data: unknown) {
  const blob = new Blob([JSON.stringify(data, null, 2) + '\n'], {
    type: 'application/json',
  })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  // Some browsers start the download after click() returns.
  setTimeout(() => URL.revokeObjectURL(url), 0)
}

function PromptView({
  className,
  onDeleted,
  prompt,
}: {
  className?: string
  onDeleted?: () => void
  prompt: Prompt
}) {
  const queryClient = useQueryClient()
  const canUpdate = useHasPermission('prompt:update')
  const canPromote = useHasPermission('prompt:promote')
  const canDelete = useHasPermission('prompt:delete')
  const [selectedN, setSelectedN] = useState<null | number>(null)
  const [promoting, setPromoting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const versionsKey = queryKeys.promptVersions(prompt.namespace, prompt.slug)
  const versionsQuery = useQuery({
    queryFn: ({ signal }) =>
      listPromptVersions(prompt.namespace, prompt.slug, signal),
    queryKey: versionsKey,
  })
  const versions = useMemo(() => versionsQuery.data ?? [], [versionsQuery.data])
  const version =
    versions.find((v) => v.n === selectedN) ??
    versions.find((v) => v.n === prompt.latest_version) ??
    versions[0]

  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.prompts() }),
      queryClient.invalidateQueries({ queryKey: versionsKey }),
    ])

  const promote = useMutation({
    mutationFn: async (values: PromoteValues) => {
      await setPromptLabel(
        prompt.namespace,
        prompt.slug,
        values.label,
        values.version,
      )
      if (values.makeDefault) {
        await setPromptDefaultLabel(prompt.namespace, prompt.slug, values.label)
      }
      return values
    },
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: async (values) => {
      setPromoting(false)
      toast.success(
        `${prompt.ref}@${values.label} now points at v${values.version}`,
      )
      await invalidate()
    },
  })

  const removeLabel = useMutation({
    mutationFn: (label: string) =>
      deletePromptLabel(prompt.namespace, prompt.slug, label),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: invalidate,
  })

  const remove = useMutation({
    mutationFn: () => deletePrompt(prompt.namespace, prompt.slug),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: async () => {
      setConfirmDelete(false)
      toast.success(`Deleted ${prompt.ref}`)
      await queryClient.invalidateQueries({
        queryKey: queryKeys.prompts(),
      })
      onDeleted?.()
    },
  })

  const shaFor = (n: number) =>
    versions.find((v) => v.n === n)?.content_sha256.slice(0, 8) ?? ''

  return (
    <div className={cn('min-w-0', className)}>
      <div className="mb-1.5 flex items-start gap-3.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2.5">
            <h1 className="text-primary font-mono text-base font-medium">
              {prompt.ref}
            </h1>
            {prompt.type && <Badge variant="neutral">{prompt.type}</Badge>}
          </div>
          <p className="text-secondary mt-1 text-sm">
            {prompt.name}
            {prompt.description ? ` — ${prompt.description}` : ''}
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {canDelete && (
            <Button
              aria-label="Delete prompt"
              className="size-9"
              onClick={() => setConfirmDelete(true)}
              size="icon"
              variant="ghost"
            >
              <Trash2 />
            </Button>
          )}
          <Button
            disabled={!version}
            onClick={() =>
              version &&
              downloadJson(
                `${prompt.namespace}-${prompt.slug}-v${version.n}.json`,
                { prompt: { ...prompt }, version },
              )
            }
            size="sm"
            variant="outline"
          >
            <Download />
            Export
          </Button>
          {canPromote && (
            <Button
              disabled={versions.length === 0}
              onClick={() => setPromoting(true)}
              size="sm"
            >
              <ArrowUpCircle />
              Promote
            </Button>
          )}
        </div>
      </div>

      <div
        className="border-warning bg-warning text-warning my-3.5 flex items-center gap-2 rounded-md border px-3 py-2 text-sm"
        style={HAIRLINE}
      >
        <TriangleAlert className="size-3.5 flex-none" />
        <span>
          Promoting {prompt.default_label} changes what every consumer of{' '}
          <span className="font-mono">
            {prompt.ref}@{prompt.default_label}
          </span>{' '}
          receives.
        </span>
      </div>

      <div className="mb-4 grid grid-cols-1 gap-2.5 md:grid-cols-3">
        {prompt.labels.map((label) => {
          const isDefault = label.name === prompt.default_label
          return (
            <div
              className={cn(
                'rounded-lg border bg-primary px-3.5 py-3',
                isDefault ? 'border-amber-border' : 'border-tertiary',
              )}
              key={label.name}
              style={HAIRLINE}
            >
              <div className="flex items-center gap-1.5">
                <Tag className="text-tertiary size-3.5" />
                <span className="text-primary font-mono text-sm font-medium">
                  {label.name}
                </span>
                {isDefault ? (
                  <span className="bg-amber-bg text-amber-text ml-auto rounded px-1.5 py-px text-[10.5px] font-medium tracking-wide uppercase">
                    default
                  </span>
                ) : (
                  canPromote && (
                    <button
                      aria-label={`Remove label ${label.name}`}
                      className="text-tertiary hover:text-primary ml-auto"
                      onClick={() => removeLabel.mutate(label.name)}
                      type="button"
                    >
                      <X className="size-3.5" />
                    </button>
                  )
                )}
              </div>
              <div className="mt-2 flex items-baseline gap-2">
                <span className="text-primary font-mono text-lg font-medium tabular-nums">
                  v{label.version}
                </span>
                <span className="text-tertiary font-mono text-xs">
                  {shaFor(label.version)}
                </span>
              </div>
              <div className="text-tertiary mt-0.5 text-xs">
                promoted by {label.updated_by} ·{' '}
                <RelativeTime value={label.updated_at} />
              </div>
            </div>
          )
        })}
      </div>

      <div className="flex items-start gap-3.5">
        <VersionList
          onSelect={setSelectedN}
          selectedN={version?.n}
          versions={versions}
        />
        {version ? (
          <VersionWorkspace
            canEdit={canUpdate}
            key={`${prompt.id}@${version.n}`}
            onSaved={setSelectedN}
            prompt={prompt}
            version={version}
          />
        ) : (
          versionsQuery.error != null && (
            <ErrorBanner
              error={versionsQuery.error}
              title="Failed to load versions"
            />
          )
        )}
      </div>

      {promoting && version && (
        <PromoteDialog
          initialVersion={version.n}
          onClose={() => setPromoting(false)}
          onSubmit={(values) => promote.mutate(values)}
          open
          pending={promote.isPending}
          prompt={prompt}
          versions={versions}
        />
      )}
      <ConfirmDialog
        description={`Deletes ${prompt.ref} and all ${prompt.latest_version} versions. Consumers that resolve it will fail.`}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate()}
        open={confirmDelete}
        title={`Delete ${prompt.ref}?`}
      />
    </div>
  )
}

function verdictVariant(verdict: PromptEvalSummary['verdict']) {
  if (verdict === 'pass') return 'success' as const
  if (verdict === 'fail') return 'danger' as const
  return 'warning' as const
}

function VersionList({
  onSelect,
  selectedN,
  versions,
}: {
  onSelect: (n: number) => void
  selectedN?: number
  versions: PromptVersion[]
}) {
  return (
    <div
      className="border-tertiary bg-primary w-67 flex-none overflow-hidden rounded-lg border"
      style={HAIRLINE}
    >
      <div
        className="border-tertiary text-tertiary border-b px-3 py-2.5 text-xs font-medium tracking-wider uppercase"
        style={{ borderBottomWidth: '0.5px' }}
      >
        Versions
      </div>
      {versions.map((v) => {
        const active = v.n === selectedN
        const evaluation = v.eval_summary as
          | null
          | PromptEvalSummary
          | undefined
        return (
          <button
            aria-current={active ? 'true' : undefined}
            className={cn(
              'block w-full border-b border-l-2 border-tertiary px-3 py-2.5 text-left last:border-b-0',
              active
                ? 'border-l-amber-border bg-amber-bg'
                : 'border-l-transparent hover:bg-secondary',
            )}
            key={v.n}
            onClick={() => onSelect(v.n)}
            style={{ borderBottomWidth: '0.5px' }}
            type="button"
          >
            <div className="flex items-center gap-2">
              <span className="text-primary font-mono text-sm font-medium">
                v{v.n}
              </span>
              <span className="text-tertiary font-mono text-xs">
                {v.content_sha256.slice(0, 8)}
              </span>
              {evaluation && (
                <Badge variant={verdictVariant(evaluation.verdict)}>
                  {evaluation.verdict}
                </Badge>
              )}
            </div>
            {v.summary && (
              <div className="text-secondary mt-0.5 truncate text-xs">
                {v.summary}
              </div>
            )}
            <div className="text-tertiary mt-1 flex items-center gap-1.5 text-xs">
              <span className="truncate">{v.created_by}</span>
              <span>·</span>
              <RelativeTime value={v.created_at} variant="narrow" />
              {v.labels.map((label) => (
                <span
                  className="bg-secondary text-secondary ml-auto rounded px-1.5 font-mono text-[11px]"
                  key={label}
                >
                  @{label}
                </span>
              ))}
            </div>
          </button>
        )
      })}
    </div>
  )
}
