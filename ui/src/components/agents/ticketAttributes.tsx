import { type KeyboardEvent, useId, useMemo, useState } from 'react'

import { Link } from 'react-router-dom'

import { useQuery } from '@tanstack/react-query'
import {
  Bug,
  CalendarClock,
  ChevronsUpDown,
  type LucideIcon,
  Plus,
  Search,
  Sparkles,
  SquareCheck,
  X,
} from 'lucide-react'

import { listOrganizationMembers, listTicketLabels } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Combobox } from '@/components/ui/combobox'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import { UserIdentity } from '@/components/ui/user-identity'
import { useDebouncedValue } from '@/hooks/useDebouncedValue'
import { useTeams } from '@/hooks/useOrgResources'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { TicketType } from '@/types'

import { ticketsPath } from './agentsNav'

export interface Person {
  display_name?: null | string
  email: string
}

/** A role row while it is edited: the name can be empty. */
export interface RoleRow {
  email: string
  name: string
}

export const TICKET_TYPES: {
  icon: LucideIcon
  label: string
  value: TicketType
}[] = [
  { icon: Bug, label: 'Bug', value: 'bug' },
  { icon: SquareCheck, label: 'Task', value: 'task' },
  { icon: Sparkles, label: 'Feature', value: 'feature' },
]

/** Role names that people often use. Any other name works too. */
const COMMON_ROLES = ['reviewer', 'qa', 'approver', 'product-owner']

/** The days before the due date when a ticket shows as due soon. */
const DUE_SOON_DAYS = 2

const DAY_MS = 86_400_000

const LABELS_SHOWN = 8

/** The limits of the API: labels and roles of a ticket, and a name. */
const MAX_LABELS = 20
const MAX_ROLES = 10
const MAX_NAME_LENGTH = 50

/** A due date, colored when it is soon or past. */
export function DueDate({ due }: { due: null | string | undefined }) {
  const state = dueState(due)
  if (!due || !state) return null
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center gap-1',
        state === 'overdue' && 'text-danger',
        state === 'soon' && 'text-warning',
      )}
      title={state === 'overdue' ? `Overdue: ${due}` : `Due ${due}`}
    >
      <CalendarClock aria-hidden className="size-3" />
      {formatDue(due)}
    </span>
  )
}

/** The due state of a date (`YYYY-MM-DD`), for its color. */
export function dueState(
  due: null | string | undefined,
  now = new Date(),
): 'due' | 'overdue' | 'soon' | undefined {
  if (!due) return undefined
  const today = Date.UTC(now.getFullYear(), now.getMonth(), now.getDate())
  const days = (Date.parse(due) - today) / DAY_MS
  if (days < 0) return 'overdue'
  return days <= DUE_SOON_DAYS ? 'soon' : 'due'
}

/**
 * Labels as chips and an input that suggests the labels of the org.
 * Each label is normalized as the API normalizes it, and an existing
 * label always wins over a new one.
 */
export function LabelInput({
  disabled,
  id,
  onChange,
  orgSlug,
  value,
}: {
  disabled?: boolean
  id?: string
  onChange: (labels: string[]) => void
  orgSlug: string
  value: string[]
}) {
  const listId = useId()
  const [draft, setDraft] = useState('')
  const [open, setOpen] = useState(false)
  // The highlighted label, by name, so that a new list of suggestions
  // cannot move the highlight to another label.
  const [picked, setPicked] = useState<null | string>(null)
  const normalized = normalizeLabel(draft)
  const q = useDebouncedValue(normalized, 150)
  const { data: found = [] } = useQuery({
    enabled: open && !!orgSlug,
    queryFn: ({ signal }) => listTicketLabels(orgSlug, q, signal),
    queryKey: queryKeys.ticketLabels(orgSlug, q),
    staleTime: 30_000,
  })
  // Suggestions for an earlier draft do not show until the lookup of
  // this draft is done; the draft itself is always an option.
  const existing =
    q === normalized ? found.filter((l) => !value.includes(l.name)) : []
  const exact = existing.find((l) => l.name === normalized)
  const options = [
    ...(exact ? [exact] : []),
    ...existing.filter((l) => l !== exact).slice(0, LABELS_SHOWN),
    ...(normalized && !exact && !value.includes(normalized)
      ? [{ count: 0, name: normalized }]
      : []),
  ]
  // A draft highlights its first option; an empty draft highlights
  // only what the arrow keys or the mouse pick.
  const pickedAt = options.findIndex((o) => o.name === picked)
  const active = pickedAt >= 0 ? pickedAt : normalized ? 0 : -1
  const full = value.length >= MAX_LABELS
  const limitError = !draft.trim()
    ? undefined
    : normalized.length > MAX_NAME_LENGTH
      ? `A label can have ${MAX_NAME_LENGTH} characters at most.`
      : full
        ? `A ticket can have ${MAX_LABELS} labels at most.`
        : undefined
  const add = (name: string) => {
    if (name && !value.includes(name)) {
      if (full || name.length > MAX_NAME_LENGTH) return
      onChange([...value, name])
    }
    setDraft('')
    setPicked(null)
  }
  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault()
      setOpen(true)
      if (!options.length) return
      const step = e.key === 'ArrowDown' ? 1 : -1
      const from = active < 0 && step < 0 ? 0 : active
      setPicked(options[(from + step + options.length) % options.length].name)
    } else if (e.key === 'Enter' || e.key === ',') {
      const option = open ? options[active] : undefined
      if (!draft.trim() && !option) return
      e.preventDefault()
      add(option?.name ?? normalized)
    } else if (e.key === 'Backspace' && !draft && value.length) {
      onChange(value.slice(0, -1))
    } else if (e.key === 'Escape' && open) {
      e.stopPropagation()
      setOpen(false)
      setPicked(null)
    }
  }
  const showMenu = open && (options.length > 0 || !!draft.trim())
  return (
    <div className="relative">
      <div
        className={cn(
          'flex min-h-9 flex-wrap items-center gap-1 rounded-md border border-input bg-primary px-1.5 py-1',
          disabled && 'opacity-50',
        )}
      >
        {value.map((label) => (
          <span
            className="bg-secondary inline-flex h-6 items-center gap-1 rounded-sm pr-1 pl-2 font-mono text-[12.5px]"
            key={label}
          >
            {label}
            <button
              aria-label={`Remove label ${label}`}
              className="text-tertiary hover:text-primary flex size-4.5 items-center justify-center rounded"
              disabled={disabled}
              onClick={() => onChange(value.filter((l) => l !== label))}
              type="button"
            >
              <X className="size-3" />
            </button>
          </span>
        ))}
        <input
          aria-activedescendant={
            showMenu && options[active] ? `${listId}-${active}` : undefined
          }
          aria-autocomplete="list"
          aria-controls={listId}
          aria-expanded={showMenu}
          className="h-6.5 min-w-15 flex-1 bg-transparent px-1 text-sm outline-none"
          disabled={disabled}
          id={id}
          onBlur={() => {
            setOpen(false)
            setPicked(null)
          }}
          onChange={(e) => {
            setDraft(e.target.value)
            setPicked(null)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={value.length ? '' : 'Add label'}
          role="combobox"
          value={draft}
        />
      </div>
      {limitError && (
        <p className="text-danger mt-1 text-xs" role="alert">
          {limitError}
        </p>
      )}
      {showMenu && (
        <div className="border-secondary bg-primary absolute inset-x-0 top-full z-50 mt-1 overflow-hidden rounded-md border shadow-md">
          {draft.trim() && normalized !== draft && (
            <div className="border-tertiary text-tertiary flex items-center gap-1.5 border-b px-3 py-2 text-[12.5px]">
              Normalized
              <span className="text-secondary font-mono">{draft}</span>→
              <span className="text-primary font-mono">
                {normalized || '(empty)'}
              </span>
            </div>
          )}
          <div aria-label="Label suggestions" id={listId} role="listbox">
            {options.map((o, i) => (
              <div
                aria-selected={i === active}
                className={cn(
                  'flex h-8.5 cursor-pointer items-center gap-2 px-3',
                  i === active && 'bg-secondary',
                )}
                id={`${listId}-${i}`}
                key={o.name}
                // Keep focus in the input.
                onMouseDown={(e) => {
                  e.preventDefault()
                  add(o.name)
                }}
                onMouseEnter={() => setPicked(o.name)}
                role="option"
              >
                <span className="bg-secondary inline-flex h-5.5 items-center rounded-sm px-2 font-mono text-[12.5px]">
                  {o.name}
                </span>
                <span className="text-tertiary text-[12.5px]">
                  {o.count
                    ? `${o.count} ${o.count === 1 ? 'ticket' : 'tickets'}`
                    : 'New label'}
                </span>
                {o === exact && (
                  <span className="text-tertiary ml-auto text-xs">
                    Existing match
                  </span>
                )}
              </div>
            ))}
          </div>
          <div className="border-tertiary text-tertiary border-t px-3 py-2 text-xs leading-snug">
            Lowercase. Spaces and underscores become hyphens; leading and
            trailing punctuation is dropped. An existing label always wins over
            a new one.
          </div>
        </div>
      )}
    </div>
  )
}

/** A label that opens the tickets with the same label. */
export function LabelLink({
  label,
  orgSlug,
}: {
  label: string
  orgSlug: string
}) {
  return (
    <Link
      className="bg-secondary text-secondary hover:bg-tertiary hover:text-primary inline-flex h-6 items-center rounded-sm px-2 font-mono text-[12.5px]"
      title={`Tickets labeled ${label}`}
      to={`${ticketsPath(orgSlug)}?${new URLSearchParams({ label })}`}
    >
      {label}
    </Link>
  )
}

/**
 * The stored form of a label or role name, as the API makes it:
 * lowercase, runs of spaces, underscores, and hyphens become one
 * hyphen, and leading and trailing punctuation goes.
 */
export function normalizeLabel(value: string): string {
  return value
    .trim()
    .toLowerCase()
    .replace(/[\s_]+/g, '-')
    .replace(/-{2,}/g, '-')
    .replace(/^[^\p{L}\p{M}\p{N}]+|[^\p{L}\p{M}\p{N}]+$/gu, '')
}

/** Choose one person of the org by name or email. */
export function PersonPicker({
  ariaLabel,
  className,
  disabled,
  loadError,
  onChange,
  people,
  placeholder = 'Search people by name or email',
  value,
}: {
  ariaLabel: string
  className?: string
  disabled?: boolean
  /** The people of the org could not load. */
  loadError?: boolean
  onChange: (email: string) => void
  people: Person[]
  placeholder?: string
  value: string
}) {
  const [open, setOpen] = useState(false)
  const picked = people.find((p) => p.email === value)
  return (
    <Popover modal onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-expanded={open}
          aria-haspopup="listbox"
          aria-label={ariaLabel}
          className={cn(
            'border-input bg-primary flex h-9 w-full min-w-0 items-center gap-2 rounded-md border px-2.5 text-left text-sm',
            disabled && 'cursor-not-allowed opacity-50',
            className,
          )}
          disabled={disabled}
          type="button"
        >
          {value ? (
            <>
              <UserIdentity
                displayName={picked?.display_name ?? undefined}
                email={value}
                linkToProfile={false}
                size="small"
              />
              <span className="text-tertiary min-w-0 flex-1 truncate text-[13px]">
                {picked?.display_name ? value : ''}
              </span>
            </>
          ) : (
            <>
              <Search aria-hidden className="text-tertiary size-3.5" />
              <span className="text-tertiary flex-1 truncate">
                {placeholder}
              </span>
            </>
          )}
          <ChevronsUpDown
            aria-hidden
            className="text-tertiary size-3.5 shrink-0"
          />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="p-0"
        style={{ width: 'var(--radix-popover-trigger-width)' }}
      >
        <Command>
          <CommandInput placeholder={placeholder} />
          <CommandList>
            <CommandEmpty>
              {loadError ? 'Could not load the people.' : 'No people match.'}
            </CommandEmpty>
            <CommandGroup>
              {people.map((p) => (
                <CommandItem
                  key={p.email}
                  onSelect={() => {
                    onChange(p.email)
                    setOpen(false)
                  }}
                  value={`${p.display_name ?? ''} ${p.email}`}
                >
                  <span className="truncate font-medium">
                    {p.display_name || p.email}
                  </span>
                  {p.display_name && (
                    <span className="text-tertiary ml-auto truncate text-xs">
                      {p.email}
                    </span>
                  )}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

/**
 * The error of each role row, or `undefined`. A blank row is fine; it
 * is left out.
 */
export function roleErrors(rows: RoleRow[]): (string | undefined)[] {
  const names = rows.map((r) => normalizeLabel(r.name))
  return rows.map((r, i) => {
    const name = names[i]
    if (!r.name.trim() && !r.email) return undefined
    if (!name) return 'Enter a role name.'
    if (!r.email) return 'Choose a person.'
    if (name.length > MAX_NAME_LENGTH)
      return `A role name can have ${MAX_NAME_LENGTH} characters at most.`
    if (names.indexOf(name) !== names.lastIndexOf(name))
      return `Another row is also the role ${name}.`
    return undefined
  })
}

/** The rows of the API's `{role: email}`. */
export function roleRows(roles: Record<string, string>): RoleRow[] {
  return Object.entries(roles).map(([name, email]) => ({ email, name }))
}

/**
 * Named roles on a ticket (reviewer, qa, ...), each held by one
 * person. Workflows read them and can hand the ticket to a role.
 */
export function RolesEditor({
  disabled,
  loadError,
  onChange,
  people,
  rows,
}: {
  disabled?: boolean
  loadError?: boolean
  onChange: (rows: RoleRow[]) => void
  people: Person[]
  rows: RoleRow[]
}) {
  const listId = useId()
  const errors = roleErrors(rows)
  const set = (i: number, row: Partial<RoleRow>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...row } : r)))
  return (
    <div className="flex flex-col gap-2">
      <datalist id={listId}>
        {COMMON_ROLES.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>
      {rows.map((row, i) => (
        <div className="flex flex-col gap-1" key={i}>
          <div className="flex items-center gap-2">
            <Input
              aria-invalid={!!errors[i]}
              aria-label={`Role ${i + 1} name`}
              className="h-9 w-36 shrink-0 font-mono text-[13px]"
              disabled={disabled}
              list={listId}
              onBlur={() => set(i, { name: normalizeLabel(row.name) })}
              onChange={(e) => set(i, { name: e.target.value })}
              placeholder="reviewer"
              value={row.name}
            />
            <PersonPicker
              ariaLabel={`Person in role ${row.name || i + 1}`}
              disabled={disabled}
              loadError={loadError}
              onChange={(email) => set(i, { email })}
              people={people}
              placeholder="Choose a person"
              value={row.email}
            />
            <Button
              aria-label={`Remove role ${row.name || i + 1}`}
              className="size-8 shrink-0"
              disabled={disabled}
              onClick={() => onChange(rows.filter((_, j) => j !== i))}
              size="icon"
              type="button"
              variant="ghost"
            >
              <X className="size-3.5" />
            </Button>
          </div>
          {errors[i] && (
            <p className="text-danger text-xs" role="alert">
              {errors[i]}
            </p>
          )}
        </div>
      ))}
      <Button
        className="text-secondary h-8 self-start px-2 text-[13px]"
        disabled={disabled || rows.length >= MAX_ROLES}
        onClick={() => onChange([...rows, { email: '', name: '' }])}
        size="sm"
        title={
          rows.length >= MAX_ROLES
            ? `A ticket can have ${MAX_ROLES} roles at most.`
            : undefined
        }
        type="button"
        variant="ghost"
      >
        <Plus className="size-3.5" />
        Add role
      </Button>
    </div>
  )
}

/** The complete rows as the API's `{role: email}`. */
export function rolesOf(rows: RoleRow[]): Record<string, string> {
  return Object.fromEntries(
    rows
      .map((r) => [normalizeLabel(r.name), r.email] as const)
      .filter(([name, email]) => name && email),
  )
}

/** Choose the team of a ticket by slug; `''` is no team. */
export function TeamPicker({
  disabled,
  onChange,
  orgSlug,
  value,
}: {
  disabled?: boolean
  onChange: (slug: string) => void
  orgSlug: string
  value: string
}) {
  const id = useId()
  const { data: teams = [] } = useTeams(orgSlug)
  return (
    <>
      <label className="sr-only" htmlFor={id}>
        Team
      </label>
      <Combobox
        disabled={disabled}
        id={id}
        onChange={onChange}
        options={[
          { label: 'No team', value: '' },
          ...teams.map((t) => ({ label: t.name, value: t.slug })),
        ]}
        placeholder="No team"
        value={value}
      />
    </>
  )
}

/** The type of a ticket, or nothing for `task`, the default. */
export function TypeIcon({ type }: { type: TicketType }) {
  if (type === 'task') return null
  const t = TICKET_TYPES.find((x) => x.value === type)
  if (!t) return null
  const Icon = t.icon
  return (
    <span className="flex shrink-0" title={t.label}>
      <Icon
        aria-hidden
        className={cn('size-3', type === 'bug' && 'text-danger')}
      />
      <span className="sr-only">{t.label}</span>
    </span>
  )
}

/** Choose the type of a ticket. */
export function TypePicker({
  disabled,
  onChange,
  value,
}: {
  disabled?: boolean
  onChange: (type: TicketType) => void
  value: TicketType
}) {
  return (
    <SegmentedControl
      ariaLabel="Type"
      className="font-sans"
      onValueChange={(v) => onChange(v as TicketType)}
      value={value}
    >
      {TICKET_TYPES.map((t) => (
        <SegmentedControlItem disabled={disabled} key={t.value} value={t.value}>
          {t.label}
        </SegmentedControlItem>
      ))}
    </SegmentedControl>
  )
}

/**
 * The active people of the org, by name, and a lookup of a display
 * name. The org roster needs only `organization:read`.
 */
export function usePeople(orgSlug: string) {
  const { data: members = [], isError } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listOrganizationMembers(orgSlug, signal),
    queryKey: queryKeys.organizationMembers(orgSlug),
    staleTime: 5 * 60_000,
  })
  const people = useMemo(
    () =>
      members
        .filter((m) => m.is_active && !!m.email)
        .sort((a, b) =>
          (a.display_name || a.email).localeCompare(b.display_name || b.email),
        ),
    [members],
  )
  const nameOf = (email: string) =>
    people.find((p) => p.email === email)?.display_name || email
  return { isError, nameOf, people }
}

function formatDue(due: string): string {
  const [y, m, d] = due.split('-').map(Number)
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
  })
}
