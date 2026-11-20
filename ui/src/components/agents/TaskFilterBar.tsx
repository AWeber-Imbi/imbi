import { type ReactNode, useState } from 'react'

import {
  ArrowLeft,
  Bot,
  ChevronRight,
  CircleDot,
  ListFilter,
  type LucideIcon,
  Tag,
  UserRound,
  X,
} from 'lucide-react'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from '@/components/ui/command'
import { EntityIcon } from '@/components/ui/entity-icon'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import { UserIdentity } from '@/components/ui/user-identity'
import { cn } from '@/lib/utils'

import { statusVariant } from './taskEvents'
import {
  activeCount,
  ME,
  NO_FILTERS,
  TASK_STATES,
  type TaskFilters,
} from './taskFilters'

const CHIP_MAX = 2
const ROW = 'data-[selected=true]:bg-foreground/6'
const PICKED = cn(
  ROW,
  'aria-checked:bg-foreground/12 aria-checked:font-medium aria-checked:data-[selected=true]:bg-foreground/16',
)

export interface FilterAgent {
  icon?: null | string
  id: string
  name: string
}

interface Field {
  icon: LucideIcon
  key: FieldKey
  label: string
  options: Option[]
}

type FieldKey = 'agent' | 'assignee' | 'label' | 'state'

interface Option {
  badge?: ReturnType<typeof statusVariant>
  icon?: ReactNode
  label: string
  value: string
}

export function AgentMark({
  agent,
  className,
}: {
  agent: FilterAgent
  className?: string
}) {
  return (
    <span
      aria-hidden
      className={cn(
        'flex size-5 shrink-0 items-center justify-center rounded bg-tertiary text-[9px] text-secondary [&_svg]:size-3!',
        className,
      )}
    >
      {agent.icon ? (
        <EntityIcon icon={agent.icon} />
      ) : (
        <span className="font-semibold">{initials(agent.name)}</span>
      )}
    </span>
  )
}

export function PersonMark({
  email,
  name,
  title = '',
}: {
  email?: null | string
  name?: string
  title?: string
}) {
  return (
    <span aria-hidden className="flex shrink-0">
      <UserIdentity
        displayName={email ? undefined : name}
        email={email}
        hideName
        kind="user"
        linkToProfile={false}
        size="small"
        title={title}
      />
    </span>
  )
}

/**
 * The search box, one Filter menu, and a chip per active filter. The
 * menu lists the fields, and a field lists its values; typing on the
 * field list also finds values.
 */
export function TaskFilterBar({
  action,
  agents,
  filters,
  labels = [],
  me,
  onChange,
  owners,
  search,
}: {
  action?: ReactNode
  agents: FilterAgent[]
  filters: TaskFilters
  /** The labels of the org to offer, most used first. */
  labels?: string[]
  me?: null | string
  onChange: (filters: TaskFilters) => void
  owners: string[]
  search: ReactNode
}) {
  const [open, setOpen] = useState(false)
  const [fieldKey, setFieldKey] = useState<FieldKey | null>(null)
  const [text, setText] = useState('')
  const myAvatar = <PersonMark email={me} name="Me" />
  const others = owners.filter((o) => o !== me)
  const localPart = (o: string) => o.split('@')[0]
  const shared = (o: string) =>
    others.some((x) => x !== o && localPart(x) === localPart(o))
  const fields: Field[] = [
    {
      icon: CircleDot,
      key: 'state',
      label: 'State',
      options: TASK_STATES.map((s) => ({
        ...s,
        badge: statusVariant({ status: s.value }),
      })),
    },
    {
      icon: UserRound,
      key: 'assignee',
      label: 'Assignee',
      options: [
        { icon: myAvatar, label: 'Me', value: ME },
        ...others.map((o) => ({
          icon: <PersonMark email={o} />,
          label: shared(o) ? o : localPart(o),
          value: o,
        })),
      ],
    },
    {
      icon: Bot,
      key: 'agent',
      label: 'Agent',
      options: agents.map((a) => ({
        icon: <AgentMark agent={a} />,
        label: a.name,
        value: a.id,
      })),
    },
    {
      icon: Tag,
      key: 'label',
      label: 'Label',
      options: [...new Set([...filters.labels, ...labels])].map((l) => ({
        label: l,
        value: l,
      })),
    },
  ]
  const field = fields.find((f) => f.key === fieldKey)
  const count = activeCount(filters)

  const show = (key: FieldKey | null) => {
    setFieldKey(key)
    setText('')
  }
  const openChange = (next: boolean) => {
    setOpen(next)
    if (!next) show(null)
  }
  const pick = (f: Field, value: string) =>
    onChange(toggled(filters, f.key, value))
  const optionOf = (f: Field, value: string): Option =>
    f.options.find((o) => o.value === value) ?? { label: value, value }
  const chips = fields
    .map((f) => ({ f, values: selected(filters, f.key) }))
    .filter(({ values }) => values.length > 0)

  return (
    <div className="border-tertiary @container flex shrink-0 flex-col gap-2 border-b p-3">
      <div className="flex items-center gap-2">
        <div className="flex min-w-0 flex-1 items-center">
          {search}
          <Popover onOpenChange={openChange} open={open}>
            <PopoverTrigger asChild>
              <Button
                aria-label="Filter"
                className="border-input h-8 shrink-0 gap-1.5 rounded-l-none border-l-0 px-2.5 text-xs"
                size="sm"
                variant="outline"
              >
                <ListFilter className="size-3.5" />
                Filter
                {count > 0 && (
                  <span className="bg-action text-action-foreground inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 font-mono text-[10px]">
                    {count}
                  </span>
                )}
              </Button>
            </PopoverTrigger>
            <PopoverContent align="end" className="w-80 p-0">
              <Command
                filter={contains}
                onKeyDown={(e) => {
                  if (e.key === 'Backspace' && !text && field) {
                    e.preventDefault()
                    show(null)
                  }
                }}
              >
                <CommandInput
                  onValueChange={setText}
                  placeholder={field ? `${field.label}…` : 'Filter by…'}
                  value={text}
                />
                <CommandList>
                  <CommandEmpty>No matches.</CommandEmpty>
                  {field ? (
                    <>
                      <CommandGroup>
                        <CommandItem
                          className={ROW}
                          forceMount
                          onSelect={() => show(null)}
                        >
                          <ArrowLeft />
                          <span className="text-secondary">{field.label}</span>
                        </CommandItem>
                      </CommandGroup>
                      <CommandSeparator />
                      <CommandGroup>
                        {field.options.map((o) => {
                          const checked = selected(filters, field.key).includes(
                            o.value,
                          )
                          return (
                            <CommandItem
                              aria-checked={checked}
                              className={PICKED}
                              key={o.value}
                              keywords={[o.value]}
                              onSelect={() => pick(field, o.value)}
                              value={`${o.label} ${o.value}`}
                            >
                              <OptionLabel option={o} />
                            </CommandItem>
                          )
                        })}
                      </CommandGroup>
                    </>
                  ) : (
                    <>
                      <CommandGroup>
                        <CommandItem
                          aria-checked={filters.assignees.includes(ME)}
                          className={PICKED}
                          onSelect={() =>
                            onChange(toggled(filters, 'assignee', ME))
                          }
                          value="Assigned to me"
                        >
                          {myAvatar}
                          Assigned to me
                        </CommandItem>
                      </CommandGroup>
                      <CommandSeparator />
                      <CommandGroup>
                        {fields.map((f) => {
                          const values = selected(filters, f.key)
                          const Icon = f.icon
                          return (
                            <CommandItem
                              className={ROW}
                              key={f.key}
                              onSelect={() => show(f.key)}
                              value={f.label}
                            >
                              <Icon className="text-tertiary" />
                              {f.label}
                              <span className="text-tertiary ml-auto flex min-w-0 items-center gap-1 text-xs">
                                <span className="max-w-36 truncate">
                                  {values
                                    .map((v) => optionOf(f, v).label)
                                    .join(', ')}
                                </span>
                                <ChevronRight />
                              </span>
                            </CommandItem>
                          )
                        })}
                      </CommandGroup>
                      {text && (
                        <CommandGroup heading="Values">
                          {fields.flatMap((f) =>
                            f.options.map((o) => (
                              <CommandItem
                                aria-checked={selected(filters, f.key).includes(
                                  o.value,
                                )}
                                className={PICKED}
                                key={`${f.key}:${o.value}`}
                                keywords={[f.label, o.value]}
                                onSelect={() =>
                                  onChange(toggled(filters, f.key, o.value))
                                }
                                value={`${f.key}:${o.label} ${o.value}`}
                              >
                                <span className="text-tertiary w-16 shrink-0 text-xs">
                                  {f.label}
                                </span>
                                <OptionLabel option={o} />
                              </CommandItem>
                            )),
                          )}
                        </CommandGroup>
                      )}
                    </>
                  )}
                </CommandList>
              </Command>
            </PopoverContent>
          </Popover>
        </div>
        {action}
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5">
          {chips.map(({ f, values }) => (
            <span
              className="border-secondary bg-secondary flex h-7 max-w-full items-center rounded-md border text-xs"
              key={f.key}
            >
              <button
                className="flex h-full min-w-0 items-center gap-1.5 overflow-hidden rounded-l-md pr-1 pl-2"
                onClick={() => {
                  show(f.key)
                  setOpen(true)
                }}
                title={`${f.label} is ${values
                  .map((v) => optionOf(f, v).label)
                  .join(', ')}`}
                type="button"
              >
                <span className="text-tertiary shrink-0">{f.label} is</span>
                {values.slice(0, CHIP_MAX).map((v, i) => (
                  <span
                    className={cn('flex min-w-0', i > 0 && 'hidden @xs:flex')}
                    key={v}
                  >
                    <OptionLabel compact option={optionOf(f, v)} />
                  </span>
                ))}
                {values.length > 1 && (
                  <span className="text-secondary shrink-0 font-medium @xs:hidden">
                    +{values.length - 1}
                  </span>
                )}
                {values.length > CHIP_MAX && (
                  <span className="text-secondary hidden shrink-0 font-medium @xs:inline">
                    +{values.length - CHIP_MAX}
                  </span>
                )}
              </button>
              <button
                aria-label={`Remove the ${f.label} filter`}
                className="text-tertiary hover:text-primary flex size-6 shrink-0 items-center justify-center rounded-r-md"
                onClick={() => onChange(cleared(filters, f.key))}
                type="button"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
          <Button
            className="text-tertiary h-7 px-1.5 text-xs"
            onClick={() => onChange(NO_FILTERS)}
            size="sm"
            variant="ghost"
          >
            Clear
          </Button>
        </div>
      )}
    </div>
  )
}

const LISTS = {
  agent: 'agents',
  assignee: 'assignees',
  label: 'labels',
  state: 'states',
} as const satisfies Record<FieldKey, keyof TaskFilters>

function cleared(filters: TaskFilters, key: FieldKey): TaskFilters {
  return { ...filters, [LISTS[key]]: [] }
}

function contains(value: string, search: string, keywords?: string[]) {
  const needle = search.trim().toLowerCase()
  return [value, ...(keywords ?? [])].some((v) =>
    v.toLowerCase().includes(needle),
  )
    ? 1
    : 0
}

function initials(name: string) {
  const words = name.split(/\s+/).filter(Boolean)
  const letters =
    words.length > 1 ? words[0][0] + words[1][0] : name.slice(0, 2)
  return letters.toUpperCase()
}

function OptionLabel({
  compact = false,
  option,
}: {
  compact?: boolean
  option: Option
}) {
  if (option.badge)
    return (
      <Badge
        className={cn('shrink-0', compact && 'px-1.5 py-0')}
        variant={option.badge}
      >
        {option.label}
      </Badge>
    )
  return (
    <span className="flex min-w-0 items-center gap-1.5">
      {option.icon}
      <span className={cn('truncate', compact && 'font-medium')}>
        {option.label}
      </span>
    </span>
  )
}

function selected(filters: TaskFilters, key: FieldKey): string[] {
  return filters[LISTS[key]]
}

function toggled(
  filters: TaskFilters,
  key: FieldKey,
  value: string,
): TaskFilters {
  const values = new Set<string>(selected(filters, key))
  if (!values.delete(value)) values.add(value)
  if (key === 'state')
    return {
      ...filters,
      states: TASK_STATES.map((s) => s.value).filter((s) => values.has(s)),
    }
  return { ...filters, [LISTS[key]]: [...values] }
}
