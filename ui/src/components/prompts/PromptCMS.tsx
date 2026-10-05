import { useMemo, useState } from 'react'

import { useNavigate, useParams } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ArrowUpCircle,
  ChevronDown,
  ChevronRight,
  Download,
  FileCode2,
  FolderClosed,
  Plus,
  Search,
  Tag,
  Trash2,
  TriangleAlert,
  X,
} from 'lucide-react'
import { toast } from 'sonner'

import {
  createPrompt,
  deletePrompt,
  deletePromptLabel,
  listPrompts,
  listPromptVersions,
  setPromptDefaultLabel,
  setPromptLabel,
} from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { RelativeTime } from '@/components/ui/RelativeTime'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type {
  Prompt,
  PromptCreate,
  PromptEvalSummary,
  PromptVersion,
} from '@/types'

import { NewPromptDialog } from './NewPromptDialog'
import { PromoteDialog, type PromoteValues } from './PromoteDialog'
import { VersionWorkspace } from './VersionWorkspace'

const HAIRLINE = { borderWidth: '0.5px' }

interface PromptTreeProps {
  canCreate: boolean
  onNew: () => void
  onSelect: (prompt: Prompt) => void
  prompts: Prompt[]
  selectedId?: string
}

/** The prompt CMS: a namespace tree and the selected prompt's versions. */
export function PromptCMS() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const { namespace, slug } = useParams()
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canCreate = useHasPermission('prompt:create')
  const [creating, setCreating] = useState(false)

  const promptsQuery = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listPrompts(orgSlug!, signal),
    queryKey: queryKeys.prompts(orgSlug ?? ''),
  })
  const prompts = useMemo(() => promptsQuery.data ?? [], [promptsQuery.data])
  const selected = prompts.find(
    (p) => p.namespace === namespace && p.slug === slug,
  )

  const create = useMutation({
    mutationFn: (body: PromptCreate) => createPrompt(orgSlug!, body),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: async (created) => {
      setCreating(false)
      await queryClient.invalidateQueries({
        queryKey: queryKeys.prompts(orgSlug!),
      })
      navigate(`/prompts/${created.namespace}/${created.slug}`)
    },
  })

  if (!orgSlug) return null

  return (
    <div className="flex h-[calc(100vh-4rem)] min-h-0">
      <PromptTree
        canCreate={canCreate}
        onNew={() => setCreating(true)}
        onSelect={(p) => navigate(`/prompts/${p.namespace}/${p.slug}`)}
        prompts={prompts}
        selectedId={selected?.id}
      />
      <main className="min-w-0 flex-1 overflow-y-auto">
        {promptsQuery.error != null && (
          <div className="p-6">
            <ErrorBanner
              error={promptsQuery.error}
              title="Failed to load prompts"
            />
          </div>
        )}
        {selected ? (
          <PromptDetail key={selected.id} orgSlug={orgSlug} prompt={selected} />
        ) : (
          <EmptyDetail
            hasPrompts={prompts.length > 0}
            loading={promptsQuery.isLoading}
          />
        )}
      </main>
      {creating && (
        <NewPromptDialog
          namespaces={[...new Set(prompts.map((p) => p.namespace))]}
          onClose={() => setCreating(false)}
          onSubmit={(body) => create.mutate(body)}
          open
          orgSlug={orgSlug}
          pending={create.isPending}
        />
      )}
    </div>
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
  URL.revokeObjectURL(url)
}

function EmptyDetail({
  hasPrompts,
  loading,
}: {
  hasPrompts: boolean
  loading: boolean
}) {
  if (loading) return null
  return (
    <div className="grid h-full place-items-center p-12">
      <div className="max-w-sm text-center">
        <div className="bg-secondary text-tertiary mx-auto mb-3 grid size-11 place-items-center rounded-lg">
          <FileCode2 className="size-5" />
        </div>
        <div className="text-primary text-[15px] font-medium">
          {hasPrompts ? 'Nothing selected' : 'No prompts yet'}
        </div>
        <p className="text-secondary mt-1 text-sm">
          {hasPrompts
            ? 'Pick a prompt to see its labels, versions, and body.'
            : 'Create a prompt to version its body, model, and parameters together.'}
        </p>
      </div>
    </div>
  )
}

function PromptDetail({
  orgSlug,
  prompt,
}: {
  orgSlug: string
  prompt: Prompt
}) {
  const navigate = useNavigate()
  const queryClient = useQueryClient()
  const canUpdate = useHasPermission('prompt:update')
  const canPromote = useHasPermission('prompt:promote')
  const canDelete = useHasPermission('prompt:delete')
  const [selectedN, setSelectedN] = useState<null | number>(null)
  const [promoting, setPromoting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)

  const versionsKey = queryKeys.promptVersions(
    orgSlug,
    prompt.namespace,
    prompt.slug,
  )
  const versionsQuery = useQuery({
    queryFn: ({ signal }) =>
      listPromptVersions(orgSlug, prompt.namespace, prompt.slug, signal),
    queryKey: versionsKey,
  })
  const versions = useMemo(() => versionsQuery.data ?? [], [versionsQuery.data])
  const version =
    versions.find((v) => v.n === selectedN) ??
    versions.find((v) => v.n === prompt.latest_version) ??
    versions[0]

  const invalidate = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: queryKeys.prompts(orgSlug) }),
      queryClient.invalidateQueries({ queryKey: versionsKey }),
    ])

  const promote = useMutation({
    mutationFn: async (values: PromoteValues) => {
      await setPromptLabel(
        orgSlug,
        prompt.namespace,
        prompt.slug,
        values.label,
        values.version,
      )
      if (values.makeDefault) {
        await setPromptDefaultLabel(
          orgSlug,
          prompt.namespace,
          prompt.slug,
          values.label,
        )
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
      deletePromptLabel(orgSlug, prompt.namespace, prompt.slug, label),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: invalidate,
  })

  const remove = useMutation({
    mutationFn: () => deletePrompt(orgSlug, prompt.namespace, prompt.slug),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: async () => {
      setConfirmDelete(false)
      toast.success(`Deleted ${prompt.ref}`)
      await queryClient.invalidateQueries({
        queryKey: queryKeys.prompts(orgSlug),
      })
      navigate('/prompts')
    },
  })

  const shaFor = (n: number) =>
    versions.find((v) => v.n === n)?.content_sha256.slice(0, 8) ?? ''

  return (
    <div className="max-w-275 px-7 pt-5 pb-16">
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
                'bg-primary rounded-lg border px-3.5 py-3',
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
            orgSlug={orgSlug}
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

function PromptTree({
  canCreate,
  onNew,
  onSelect,
  prompts,
  selectedId,
}: PromptTreeProps) {
  const [filter, setFilter] = useState('')
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set())

  const groups = useMemo(() => {
    const needle = filter.trim().toLowerCase()
    const byNamespace = new Map<string, Prompt[]>()
    for (const p of prompts) {
      if (
        needle &&
        !p.ref.toLowerCase().includes(needle) &&
        !p.name.toLowerCase().includes(needle)
      ) {
        continue
      }
      byNamespace.set(p.namespace, [...(byNamespace.get(p.namespace) ?? []), p])
    }
    return [...byNamespace.entries()].sort(([a], [b]) => a.localeCompare(b))
  }, [filter, prompts])

  const toggle = (ns: string) =>
    setCollapsed((current) => {
      const next = new Set(current)
      if (next.has(ns)) next.delete(ns)
      else next.add(ns)
      return next
    })

  return (
    <aside
      className="border-tertiary bg-primary flex w-74 flex-none flex-col border-r"
      style={{ borderRightWidth: '0.5px' }}
    >
      <div className="flex items-center gap-2 px-3 pt-3 pb-2">
        <span className="text-tertiary text-xs font-medium tracking-wider uppercase">
          Prompts
        </span>
        <span className="text-tertiary ml-auto font-mono text-xs">
          {prompts.length} · {new Set(prompts.map((p) => p.namespace)).size}{' '}
          namespaces
        </span>
      </div>
      <div className="flex items-center gap-2 px-3 pb-2">
        <div className="relative flex-1">
          <Search className="text-tertiary absolute top-2 left-2.5 size-3.5" />
          <Input
            aria-label="Filter prompts"
            className="h-8 pl-8 text-sm"
            onChange={(e) => setFilter(e.target.value)}
            placeholder="Filter prompts"
            value={filter}
          />
        </div>
        {canCreate && (
          <Button
            aria-label="New prompt"
            className="size-8"
            onClick={onNew}
            size="icon"
            variant="outline"
          >
            <Plus />
          </Button>
        )}
      </div>
      <nav aria-label="Prompts" className="flex-1 overflow-y-auto px-2 pb-6">
        {groups.map(([ns, items]) => {
          const open = !collapsed.has(ns) || filter.trim() !== ''
          return (
            <div key={ns}>
              <button
                aria-expanded={open}
                className="text-secondary hover:bg-secondary flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-sm"
                onClick={() => toggle(ns)}
                type="button"
              >
                {open ? (
                  <ChevronDown className="size-3.5" />
                ) : (
                  <ChevronRight className="size-3.5" />
                )}
                <FolderClosed className="text-tertiary size-3.5" />
                <span className="text-primary truncate font-mono text-xs font-medium">
                  {ns}
                </span>
                <span className="text-tertiary ml-auto font-mono text-xs">
                  {items.length}
                </span>
              </button>
              {open &&
                items.map((p) => {
                  const active = p.id === selectedId
                  return (
                    <button
                      aria-current={active ? 'page' : undefined}
                      className={cn(
                        'flex w-full items-center gap-2 rounded-md border-l-2 py-1.5 pr-2 pl-7 text-left text-sm',
                        active
                          ? 'border-amber-border bg-amber-bg text-primary'
                          : 'text-secondary hover:bg-secondary border-transparent',
                      )}
                      key={p.id}
                      onClick={() => onSelect(p)}
                      type="button"
                    >
                      <FileCode2 className="text-tertiary size-3.5 flex-none" />
                      <span
                        className={cn(
                          'truncate font-mono text-xs',
                          active && 'font-medium',
                        )}
                      >
                        {p.slug}
                      </span>
                      <span className="text-tertiary ml-auto font-mono text-xs">
                        v{p.latest_version}
                      </span>
                    </button>
                  )
                })}
            </div>
          )
        })}
      </nav>
    </aside>
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
