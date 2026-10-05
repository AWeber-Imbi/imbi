import { useMemo, useState } from 'react'

import { useSearchParams } from 'react-router-dom'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ChevronDown,
  ChevronRight,
  FileCode2,
  FolderClosed,
  Plus,
  Search,
} from 'lucide-react'
import { toast } from 'sonner'

import { createPrompt, listPrompts } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { Prompt, PromptCreate } from '@/types'

import { NewPromptDialog } from './NewPromptDialog'
import { PromptEditor } from './PromptEditor'

interface PromptTreeProps {
  canCreate: boolean
  onNew: () => void
  onSelect: (prompt: Prompt) => void
  prompts: Prompt[]
  selectedId?: string
}

/**
 * Every prompt in the organization (or one namespace) as a tree, with
 * the selected prompt open in a `PromptEditor`. The selection lives in
 * the `?prompt=namespace/slug` search param, so it works on any route.
 */
export function PromptLibrary({ namespace }: { namespace?: string }) {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const canCreate = useHasPermission('prompt:create')
  const [creating, setCreating] = useState(false)

  const promptsQuery = useQuery({
    queryFn: ({ signal }) => listPrompts(signal),
    queryKey: queryKeys.prompts(),
  })
  const prompts = useMemo(
    () =>
      (promptsQuery.data ?? []).filter(
        (p) => namespace === undefined || p.namespace === namespace,
      ),
    [namespace, promptsQuery.data],
  )
  const selectedRef = searchParams.get('prompt')
  const selected = prompts.find((p) => p.ref === selectedRef)

  const select = (ref: null | string) =>
    setSearchParams(
      (params) => {
        const next = new URLSearchParams(params)
        if (ref) next.set('prompt', ref)
        else next.delete('prompt')
        return next
      },
      { replace: true },
    )

  const create = useMutation({
    mutationFn: (body: PromptCreate) => createPrompt(body),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: async (created) => {
      setCreating(false)
      await queryClient.invalidateQueries({
        queryKey: queryKeys.prompts(),
      })
      select(created.ref)
    },
  })

  return (
    <div
      className="border-tertiary bg-primary flex h-[calc(100vh-12rem)] min-h-120 overflow-hidden rounded-lg border"
      style={{ borderWidth: '0.5px' }}
    >
      <PromptTree
        canCreate={canCreate}
        onNew={() => setCreating(true)}
        onSelect={(p) => select(p.ref)}
        prompts={prompts}
        selectedId={selected?.id}
      />
      <div className="min-w-0 flex-1 overflow-y-auto">
        {promptsQuery.error != null && (
          <div className="p-6">
            <ErrorBanner
              error={promptsQuery.error}
              title="Failed to load prompts"
            />
          </div>
        )}
        {selected ? (
          <PromptEditor
            className="px-6 pt-5 pb-12"
            key={selected.id}
            namespace={selected.namespace}
            onDeleted={() => select(null)}
            slug={selected.slug}
          />
        ) : (
          <EmptyDetail
            hasPrompts={prompts.length > 0}
            loading={promptsQuery.isLoading}
          />
        )}
      </div>
      {creating && (
        <NewPromptDialog
          defaults={namespace ? { namespace } : undefined}
          namespaces={[...new Set(prompts.map((p) => p.namespace))]}
          onClose={() => setCreating(false)}
          onSubmit={(body) => create.mutate(body)}
          open
          pending={create.isPending}
        />
      )}
    </div>
  )
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
                          : 'border-transparent text-secondary hover:bg-secondary',
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
