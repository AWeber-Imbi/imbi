import { type ReactNode, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import { RequiredAsterisk } from '@/components/ui/required-asterisk'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { cn } from '@/lib/utils'

import { Chip, ChipGroup } from './controls'
import {
  changedFields,
  DELIVERY_MODES,
  duration,
  PURPOSE_PATTERN,
  type SecretBinding,
  type SecretGrant,
  SETUP_PURPOSES,
  titleList,
} from './types'

interface Form {
  agent_ids: string[]
  binding_ids: string[]
  delivery_modes: string[]
  description: string
  max_ttl_seconds: string
  project_ids: string[]
  purposes: string[]
}

interface GrantDialogProps {
  agents: Option[]
  bindings: SecretBinding[]
  error?: unknown
  isPending: boolean
  onClose: () => void
  onSubmit: (body: Record<string, unknown>) => void
  /** The grant to edit. The dialog then sends only the changed fields. */
  original?: SecretGrant
  projects: Option[]
  /** Purposes that grants name already, offered next to the setup ones. */
  purposes: string[]
}

interface Option {
  hint?: string
  label: string
  value: string
}

/** The create or edit dialog for a grant. */
// fallow-ignore-next-line complexity
export function GrantDialog({
  agents,
  bindings,
  error,
  isPending,
  onClose,
  onSubmit,
  original,
  projects,
  purposes,
}: GrantDialogProps) {
  const [form, setForm] = useState<Form>(() => ({
    agent_ids: original?.agent_ids ?? [],
    binding_ids: original?.binding_ids ?? [],
    delivery_modes: original?.delivery_modes ?? [],
    description: original?.description ?? '',
    max_ttl_seconds: String(original?.max_ttl_seconds ?? 900),
    project_ids: original?.project_ids ?? [],
    purposes: original?.purposes ?? [],
  }))
  const [someProjects, setSomeProjects] = useState(
    !!original?.project_ids.length,
  )
  const [slug, setSlug] = useState('')
  const set = <K extends keyof Form>(key: K, value: Form[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }))

  const chosen = bindings.filter((b) => form.binding_ids.includes(b.id))
  const allowed = allowedModes(chosen)
  // A grant can only narrow its bindings, so a change of bindings selects
  // every mode that they all allow. Clear the ones the agents do not use.
  const setBindings = (ids: string[]) =>
    setForm((prev) => ({
      ...prev,
      binding_ids: ids,
      delivery_modes: allowedModes(bindings.filter((b) => ids.includes(b.id))),
    }))

  const purposeOptions = [
    ...new Set([...SETUP_PURPOSES, ...purposes, ...form.purposes]),
  ].sort()
  const canAdd = PURPOSE_PATTERN.test(slug) && !form.purposes.includes(slug)
  const addSlug = () => {
    if (!canAdd) return
    set('purposes', [...form.purposes, slug])
    setSlug('')
  }

  const ttl = Number(form.max_ttl_seconds)
  const projectIds = someProjects ? form.project_ids : []
  const ready =
    form.agent_ids.length > 0 &&
    form.binding_ids.length > 0 &&
    form.purposes.length > 0 &&
    form.delivery_modes.length > 0 &&
    form.delivery_modes.every((m) => allowed.includes(m)) &&
    ttl > 0 &&
    (!someProjects || form.project_ids.length > 0)

  const submit = () => {
    const body: Record<string, unknown> = {
      agent_ids: form.agent_ids,
      binding_ids: form.binding_ids,
      delivery_modes: form.delivery_modes,
      max_ttl_seconds: ttl,
      project_ids: projectIds,
      purposes: form.purposes,
    }
    const description = form.description.trim()
    if (description || original) body.description = description
    if (!original) return onSubmit(body)
    const changed = changedFields(body, original)
    if (!Object.keys(changed).length) return onClose()
    onSubmit(changed)
  }

  const blocked = DELIVERY_MODES.filter((m) => !allowed.includes(m))

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open>
      <DialogContent className="max-w-180">
        <DialogHeader>
          <DialogTitle>{original ? 'Edit grant' : 'New grant'}</DialogTitle>
          <DialogDescription>
            The broker allows a request only when an enabled grant matches all
            of it.
          </DialogDescription>
        </DialogHeader>
        <Tabs className="px-6" defaultValue="settings">
          <TabsList>
            <TabsTrigger value="settings">Settings</TabsTrigger>
            <TabsTrigger className="gap-1.5" value="projects">
              Projects
              <span className="bg-secondary text-secondary rounded-full px-1.5 text-xs">
                {someProjects ? form.project_ids.length : 'All'}
              </span>
            </TabsTrigger>
          </TabsList>
          <div className="h-[60vh] overflow-y-auto py-4">
            {error != null && (
              <div className="mb-4">
                <ErrorBanner error={error} title="Failed to save the grant" />
              </div>
            )}
            <TabsContent className="mt-0 space-y-5" value="settings">
              <div className="grid grid-cols-2 gap-4">
                <Picker
                  label="Agents"
                  onChange={(ids) => set('agent_ids', ids)}
                  options={agents}
                  selected={form.agent_ids}
                />
                <Picker
                  label="Bindings"
                  onChange={setBindings}
                  options={bindings.map((b) => ({
                    label: b.reference,
                    value: b.id,
                  }))}
                  selected={form.binding_ids}
                />
              </div>
              <ChipGroup
                hint="the slug an agent sends with its request"
                label="Purposes"
              >
                {purposeOptions.map((p) => (
                  <Chip
                    checked={form.purposes.includes(p)}
                    key={p}
                    label={p}
                    mono
                    onChange={(on) =>
                      set('purposes', toggle(form.purposes, p, on))
                    }
                  />
                ))}
                <Input
                  aria-label="Add a purpose"
                  className="h-8 w-36 font-mono text-xs"
                  onBlur={addSlug}
                  onChange={(e) => setSlug(e.target.value.trim())}
                  onKeyDown={(e) => {
                    if (e.key !== 'Enter') return
                    e.preventDefault()
                    addSlug()
                  }}
                  placeholder="+ Add slug"
                  value={slug}
                />
              </ChipGroup>
              <ChipGroup label="Delivery modes">
                {DELIVERY_MODES.map((mode) => (
                  <Chip
                    checked={form.delivery_modes.includes(mode)}
                    // A mode that a binding stopped allowing stays
                    // enabled while checked, so it can be cleared.
                    disabled={
                      !allowed.includes(mode) &&
                      !form.delivery_modes.includes(mode)
                    }
                    key={mode}
                    label={titleList([mode])}
                    onChange={(on) =>
                      set(
                        'delivery_modes',
                        toggle(form.delivery_modes, mode, on),
                      )
                    }
                    title={
                      allowed.includes(mode)
                        ? undefined
                        : `Not allowed by ${blockers(chosen, mode)}`
                    }
                  />
                ))}
                {blocked.length > 0 && (
                  <p className="text-tertiary w-full text-xs">
                    {titleList(blocked)} {blocked.length > 1 ? 'are' : 'is'}{' '}
                    off: a chosen binding does not allow{' '}
                    {blocked.length > 1 ? 'them' : 'it'}.
                  </p>
                )}
              </ChipGroup>
              <div className="grid grid-cols-[auto_1fr] gap-4">
                <label className="space-y-1.5 text-sm font-medium">
                  <span>Maximum TTL</span>
                  <span className="flex items-center gap-2">
                    <Input
                      className="w-24"
                      min={1}
                      onChange={(e) => set('max_ttl_seconds', e.target.value)}
                      type="number"
                      value={form.max_ttl_seconds}
                    />
                    <span className="text-tertiary font-normal">
                      sec{ttl > 0 && ` · ${duration(ttl)}`}
                    </span>
                  </span>
                </label>
                <label className="space-y-1.5 text-sm font-medium">
                  <span>
                    Description{' '}
                    <span className="text-tertiary font-normal">
                      (optional)
                    </span>
                  </span>
                  <Input
                    onChange={(e) => set('description', e.target.value)}
                    placeholder="Why this grant exists"
                    value={form.description}
                  />
                </label>
              </div>
            </TabsContent>
            <TabsContent
              className="mt-0 h-full flex-col gap-4 data-[state=active]:flex"
              value="projects"
            >
              <fieldset className="grid shrink-0 grid-cols-2 gap-2">
                <legend className="mb-2 text-sm font-medium">
                  Where agents can use this grant
                </legend>
                {[
                  [false, 'All projects', 'Including ones added later.'],
                  [true, 'Selected projects', 'Only the ones checked below.'],
                ].map(([value, title, text]) => (
                  <label
                    className="border-secondary has-checked:border-action flex cursor-pointer gap-2.5 rounded-lg border px-3 py-2.5"
                    key={String(value)}
                  >
                    <input
                      checked={someProjects === value}
                      className="mt-0.5"
                      name="scope"
                      onChange={() => setSomeProjects(value as boolean)}
                      type="radio"
                    />
                    <span>
                      <span className="block text-sm font-medium">{title}</span>
                      <span className="text-secondary block text-xs">
                        {text}
                      </span>
                    </span>
                  </label>
                ))}
              </fieldset>
              {someProjects && (
                <Picker
                  label="Projects"
                  onChange={(ids) => set('project_ids', ids)}
                  options={projects}
                  selected={form.project_ids}
                  tall
                />
              )}
            </TabsContent>
          </div>
        </Tabs>
        <DialogFooter className="items-center gap-4">
          <p className="text-secondary mr-auto min-w-0 text-xs">
            {summary(form, chosen, someProjects, ttl)}
          </p>
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
          <Button disabled={isPending || !ready} onClick={submit}>
            {original ? 'Save' : 'Create grant'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

/**
 * The delivery modes that every chosen binding allows. The broker needs
 * a request's mode in its binding and in its grant, so a grant mode
 * outside this set can never match.
 */
function allowedModes(chosen: SecretBinding[]): string[] {
  return DELIVERY_MODES.filter((mode) =>
    chosen.every((b) => b.allowed_delivery_modes.includes(mode)),
  )
}

const blockers = (chosen: SecretBinding[], mode: string) =>
  chosen
    .filter((b) => !b.allowed_delivery_modes.includes(mode))
    .map((b) => b.reference)
    .join(', ')

const toggle = (list: string[], value: string, on: boolean) =>
  on ? [...list, value] : list.filter((v) => v !== value)

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? '' : 's'}`

/** A filtered checkbox list, with a count, "Selected only", and Clear. */
// fallow-ignore-next-line complexity
function Picker({
  label,
  onChange,
  options,
  selected,
  tall = false,
}: {
  label: string
  onChange: (ids: string[]) => void
  options: Option[]
  selected: string[]
  tall?: boolean
}) {
  const [query, setQuery] = useState('')
  const [onlySelected, setOnlySelected] = useState(false)
  const needle = query.trim().toLowerCase()
  const shown = options.filter(
    (o) =>
      (!onlySelected || selected.includes(o.value)) &&
      (!needle || o.label.toLowerCase().includes(needle)),
  )
  return (
    <fieldset className={cn('min-w-0', tall && 'flex min-h-0 flex-1 flex-col')}>
      <legend className="mb-2 flex w-full justify-between text-sm font-medium">
        <span>
          {label} <RequiredAsterisk />
        </span>
        <span className="text-tertiary font-normal">
          {selected.length} of {options.length}
        </span>
      </legend>
      <div
        className={cn(
          'overflow-hidden rounded-lg border border-tertiary',
          tall && 'flex min-h-0 flex-1 flex-col',
        )}
      >
        <div className="border-tertiary border-b p-2">
          <Input
            aria-label={`Filter ${label.toLowerCase()}`}
            className="h-8"
            onChange={(e) => setQuery(e.target.value)}
            placeholder={`Filter ${label.toLowerCase()}`}
            value={query}
          />
        </div>
        <div
          className={cn('overflow-y-auto', tall ? 'min-h-44 flex-1' : 'h-44')}
        >
          {shown.map((o) => (
            <label
              className="hover:bg-secondary flex h-9 cursor-pointer items-center gap-3 px-3 text-sm"
              key={o.value}
            >
              <Checkbox
                aria-label={o.label}
                checked={selected.includes(o.value)}
                onCheckedChange={(on) =>
                  onChange(toggle(selected, o.value, on === true))
                }
              />
              <span className="min-w-0 flex-1 truncate font-medium">
                {o.label}
              </span>
              {o.hint && (
                <span className="text-tertiary text-xs">{o.hint}</span>
              )}
            </label>
          ))}
          {!shown.length && (
            <p className="text-tertiary px-3 py-2 text-sm">No matches.</p>
          )}
        </div>
        <div className="border-tertiary flex items-center justify-between border-t px-3 py-1.5 text-xs">
          <label className="flex items-center gap-2">
            <Checkbox
              checked={onlySelected}
              onCheckedChange={(on) => setOnlySelected(on === true)}
            />
            Selected only
          </label>
          <button
            className="text-secondary hover:text-primary disabled:opacity-50"
            disabled={!selected.length}
            onClick={() => onChange([])}
            type="button"
          >
            Clear
          </button>
        </div>
      </div>
    </fieldset>
  )
}

// fallow-ignore-next-line complexity
function summary(
  form: Form,
  chosen: SecretBinding[],
  someProjects: boolean,
  ttl: number,
): ReactNode {
  if (!form.agent_ids.length || !chosen.length) return null
  return (
    <>
      <strong className="text-primary font-medium">
        {plural(form.agent_ids.length, 'agent')}
      </strong>{' '}
      {form.agent_ids.length === 1 ? 'gets' : 'get'}{' '}
      <span className="text-primary font-mono">
        {chosen.map((b) => b.reference).join(', ')}
      </span>
      {form.purposes.length > 0 && (
        <>
          {' '}
          for{' '}
          <span className="text-primary font-mono">
            {form.purposes.join(', ')}
          </span>
        </>
      )}
      {form.delivery_modes.length > 0 &&
        ` by ${titleList(form.delivery_modes).toLowerCase()}`}
      {ttl > 0 && `, ${duration(ttl)}`},{' '}
      {someProjects
        ? `in ${plural(form.project_ids.length, 'project')}`
        : 'all projects'}
      .
    </>
  )
}
