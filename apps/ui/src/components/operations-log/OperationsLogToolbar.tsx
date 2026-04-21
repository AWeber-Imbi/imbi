import {
  forwardRef,
  useMemo,
  useState,
  type ComponentPropsWithoutRef,
  type ReactNode,
} from 'react'
import {
  Box,
  Check,
  ChevronDown,
  Filter,
  GitBranch,
  Layers,
  List,
  Search,
} from 'lucide-react'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Input } from '@/components/ui/input'
import { cn } from '@/lib/utils'
import { sortEnvironments } from '@/lib/utils'
import {
  OPERATIONS_LOG_ENTRY_TYPES,
  type Environment,
  type OperationsLogEntryType,
} from '@/types'
import type { OperationsLogView, TimeRange } from './opsLogHelpers'

const RANGES: { key: TimeRange; label: string }[] = [
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
  { key: '90d', label: '90d' },
  { key: 'all', label: 'All' },
]

export interface ToolbarCounts {
  type: Partial<Record<OperationsLogEntryType, number>>
  env: Record<string, number>
  project: Record<string, number>
}

interface ToolbarProps {
  counts: ToolbarCounts
  range: TimeRange
  onRange: (r: TimeRange) => void
  entryTypes: OperationsLogEntryType[]
  onEntryTypes: (ts: OperationsLogEntryType[]) => void
  environmentSlugs: string[]
  onEnvironmentSlugs: (slugs: string[]) => void
  environments: Environment[]
  projectSlugs: string[]
  onProjectSlugs: (slugs: string[]) => void
  projectNames: Map<string, string>
  view: OperationsLogView
  onView: (v: OperationsLogView) => void
}

function toggle<T>(arr: T[], value: T): T[] {
  return arr.includes(value) ? arr.filter((x) => x !== value) : [...arr, value]
}

function pluralLabel(
  singular: string,
  count: number,
  selectedLabel?: string,
): string {
  if (count === 0) return singular
  if (count === 1 && selectedLabel) return selectedLabel
  return `${count} selected`
}

type TriggerButtonProps = ComponentPropsWithoutRef<'button'> & {
  icon: ReactNode
  label: string
  value?: string
  count?: number
}

// Radix's DropdownMenuTrigger (used with `asChild`) composes its ref and
// event handlers onto the direct child. Using forwardRef and spreading
// the received props lets Radix wire open/close, focus, and a11y
// attributes onto the real <button>.
const TriggerButton = forwardRef<HTMLButtonElement, TriggerButtonProps>(
  function TriggerButton(
    { icon, label, value, count, className, ...props },
    ref,
  ) {
    return (
      <button
        ref={ref}
        type="button"
        className={cn(
          'inline-flex h-9 items-center gap-2 rounded-md border border-tertiary bg-primary px-3 text-sm text-secondary transition-colors hover:bg-secondary hover:text-primary',
          className,
        )}
        {...props}
      >
        <span className="flex h-4 w-4 items-center justify-center text-tertiary">
          {icon}
        </span>
        <span className={cn(value && 'text-primary')}>{value ?? label}</span>
        {count !== undefined ? (
          <span className="ml-0.5 rounded bg-secondary px-1.5 text-[11px] tabular-nums text-tertiary">
            {count}
          </span>
        ) : null}
        <ChevronDown className="h-3.5 w-3.5 text-tertiary" />
      </button>
    )
  },
)

interface FacetOption {
  key: string
  label: string
  count: number
}

function FacetDropdown({
  icon,
  label,
  allLabel,
  selected,
  onChange,
  options,
  contentClassName,
}: {
  icon: React.ReactNode
  label: string
  allLabel: string
  selected: string[]
  onChange: (next: string[]) => void
  options: FacetOption[]
  contentClassName?: string
}) {
  const single =
    selected.length === 1
      ? (options.find((o) => o.key === selected[0])?.label ?? selected[0])
      : undefined
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <TriggerButton
          icon={icon}
          label={label}
          value={
            selected.length === 0
              ? undefined
              : (single ?? `${selected.length} selected`)
          }
        />
      </DropdownMenuTrigger>
      <DropdownMenuContent
        align="start"
        className={contentClassName ?? 'min-w-[200px]'}
      >
        <DropdownMenuCheckboxItem
          checked={selected.length === 0}
          onSelect={(e) => {
            e.preventDefault()
            onChange([])
          }}
        >
          {allLabel}
        </DropdownMenuCheckboxItem>
        <DropdownMenuSeparator />
        {options.map((o) => (
          <DropdownMenuCheckboxItem
            key={o.key}
            checked={selected.includes(o.key)}
            onSelect={(e) => {
              e.preventDefault()
              onChange(toggle(selected, o.key))
            }}
          >
            <span className="flex-1">{o.label}</span>
            <span className="ml-3 text-xs text-tertiary">{o.count}</span>
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}

export function OperationsLogToolbar({
  counts,
  range,
  onRange,
  entryTypes,
  onEntryTypes,
  environmentSlugs,
  onEnvironmentSlugs,
  environments,
  projectSlugs,
  onProjectSlugs,
  projectNames,
  view,
  onView,
}: ToolbarProps) {
  const [projectQuery, setProjectQuery] = useState('')

  const availableEntryTypes = useMemo(
    () => OPERATIONS_LOG_ENTRY_TYPES.filter((t) => (counts.type[t] ?? 0) > 0),
    [counts.type],
  )
  const orderedEnvs = useMemo(
    () =>
      sortEnvironments(environments).filter(
        (env) =>
          (counts.env[env.slug] ?? 0) > 0 ||
          environmentSlugs.includes(env.slug),
      ),
    [environments, counts.env, environmentSlugs],
  )
  const projectEntries = useMemo(() => {
    const all = Object.entries(counts.project).sort(
      (a, b) =>
        b[1] - a[1] ||
        (projectNames.get(a[0]) ?? a[0]).localeCompare(
          projectNames.get(b[0]) ?? b[0],
        ),
    )
    const q = projectQuery.toLowerCase().trim()
    if (!q) return all
    return all.filter(([slug]) => {
      const name = (projectNames.get(slug) ?? slug).toLowerCase()
      return slug.toLowerCase().includes(q) || name.includes(q)
    })
  }, [counts.project, projectNames, projectQuery])

  const entryTypeOptions: FacetOption[] = useMemo(
    () =>
      availableEntryTypes.map((t) => ({
        key: t,
        label: t,
        count: counts.type[t] ?? 0,
      })),
    [availableEntryTypes, counts.type],
  )
  const environmentOptions: FacetOption[] = useMemo(
    () =>
      orderedEnvs.map((env) => ({
        key: env.slug,
        label: env.name,
        count: counts.env[env.slug] ?? 0,
      })),
    [orderedEnvs, counts.env],
  )

  const projectTriggerValue = pluralLabel(
    'Project',
    projectSlugs.length,
    projectSlugs[0]
      ? (projectNames.get(projectSlugs[0]) ?? projectSlugs[0])
      : undefined,
  )

  return (
    <div className="mb-4 flex flex-wrap items-center gap-2">
      <div
        role="group"
        aria-label="Time range"
        className="inline-flex items-center rounded-md border border-tertiary bg-secondary p-0.5"
      >
        {RANGES.map((r) => (
          <button
            key={r.key}
            type="button"
            onClick={() => onRange(r.key)}
            className={cn(
              'rounded px-2.5 py-1 text-xs font-medium transition-colors',
              range === r.key
                ? 'bg-primary text-primary shadow-sm'
                : 'text-secondary hover:text-primary',
            )}
          >
            {r.label}
          </button>
        ))}
      </div>

      <span className="mx-1 h-6 w-px bg-tertiary" aria-hidden />

      <FacetDropdown
        icon={<Filter className="h-3.5 w-3.5" />}
        label="Entry Type"
        allLabel="All entry types"
        selected={entryTypes}
        onChange={(next) => onEntryTypes(next as OperationsLogEntryType[])}
        options={entryTypeOptions}
      />

      <FacetDropdown
        icon={<Layers className="h-3.5 w-3.5" />}
        label="Environment"
        allLabel="All environments"
        selected={environmentSlugs}
        onChange={onEnvironmentSlugs}
        options={environmentOptions}
        contentClassName="min-w-[220px]"
      />

      <DropdownMenu
        onOpenChange={(open) => {
          if (!open) setProjectQuery('')
        }}
      >
        <DropdownMenuTrigger asChild>
          <TriggerButton
            icon={<Box className="h-3.5 w-3.5" />}
            label="Project"
            value={projectSlugs.length > 0 ? projectTriggerValue : undefined}
            count={projectSlugs.length > 0 ? undefined : projectEntries.length}
          />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start" className="min-w-[260px] p-0">
          <div className="relative border-b border-tertiary p-2">
            <Search className="pointer-events-none absolute left-4 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-tertiary" />
            <Input
              value={projectQuery}
              onChange={(e) => setProjectQuery(e.target.value)}
              placeholder="Filter projects…"
              className="h-8 pl-7 text-sm"
              autoFocus
            />
          </div>
          <div className="max-h-72 overflow-y-auto py-1">
            <button
              type="button"
              onClick={() => onProjectSlugs([])}
              className={cn(
                'flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm transition-colors',
                projectSlugs.length === 0 && 'bg-secondary text-primary',
                projectSlugs.length > 0 && 'text-secondary hover:bg-secondary',
              )}
            >
              <Check
                className={cn(
                  'h-3.5 w-3.5',
                  projectSlugs.length > 0 && 'invisible',
                )}
              />
              All projects
            </button>
            {projectEntries.map(([slug, c]) => {
              const checked = projectSlugs.includes(slug)
              return (
                <button
                  key={slug}
                  type="button"
                  onClick={() => onProjectSlugs(toggle(projectSlugs, slug))}
                  className={cn(
                    'flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm transition-colors',
                    checked && 'bg-secondary text-primary',
                    !checked && 'text-secondary hover:bg-secondary',
                  )}
                  title={projectNames.get(slug) ?? slug}
                >
                  <Check
                    className={cn('h-3.5 w-3.5', !checked && 'invisible')}
                  />
                  <span className="flex-1 truncate font-mono text-[13px]">
                    {slug}
                  </span>
                  <span className="ml-3 text-xs text-tertiary">{c}</span>
                </button>
              )
            })}
            {projectEntries.length === 0 ? (
              <div className="px-3 py-2 text-xs text-tertiary">
                No projects match.
              </div>
            ) : null}
          </div>
        </DropdownMenuContent>
      </DropdownMenu>

      <div
        role="group"
        aria-label="View"
        className="ml-auto inline-flex h-9 items-center rounded-md border border-tertiary bg-secondary p-1"
      >
        <button
          type="button"
          onClick={() => onView('stream')}
          className={cn(
            'inline-flex h-full items-center gap-1.5 rounded px-3 text-xs font-medium transition-colors',
            view === 'stream'
              ? 'bg-primary text-primary shadow-sm'
              : 'text-secondary hover:text-primary',
          )}
        >
          <List className="h-3.5 w-3.5" /> Stream
        </button>
        <button
          type="button"
          onClick={() => onView('grouped')}
          className={cn(
            'inline-flex h-full items-center gap-1.5 rounded px-3 text-xs font-medium transition-colors',
            view === 'grouped'
              ? 'bg-primary text-primary shadow-sm'
              : 'text-secondary hover:text-primary',
          )}
        >
          <GitBranch className="h-3.5 w-3.5" /> Releases
        </button>
      </div>
    </div>
  )
}
