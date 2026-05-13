import {
  type ComponentPropsWithoutRef,
  forwardRef,
  type ReactNode,
  useMemo,
  useState,
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
  type Environment,
  OPERATIONS_LOG_ENTRY_TYPES,
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
  env: Record<string, number>
  project: Record<string, number>
  type: Partial<Record<OperationsLogEntryType, number>>
}

interface ToolbarProps {
  counts: ToolbarCounts
  entryTypes: OperationsLogEntryType[]
  environments: Environment[]
  environmentSlugs: string[]
  hideProjectFilter?: boolean
  hideTimeRange?: boolean
  onEntryTypes: (ts: OperationsLogEntryType[]) => void
  onEnvironmentSlugs: (slugs: string[]) => void
  onProjectSlugs: (slugs: string[]) => void
  onRange: (r: TimeRange) => void
  onView: (v: OperationsLogView) => void
  projectNames: Map<string, string>
  projectSlugs: string[]
  range: TimeRange
  view: OperationsLogView
}

type TriggerButtonProps = ComponentPropsWithoutRef<'button'> & {
  count?: number
  icon: ReactNode
  label: string
  value?: string
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

function toggle<T>(arr: T[], value: T): T[] {
  return arr.includes(value) ? arr.filter((x) => x !== value) : [...arr, value]
}

// Radix's DropdownMenuTrigger (used with `asChild`) composes its ref and
// event handlers onto the direct child. Using forwardRef and spreading
// the received props lets Radix wire open/close, focus, and a11y
// attributes onto the real <button>.
const TriggerButton = forwardRef<HTMLButtonElement, TriggerButtonProps>(
  function TriggerButton(
    { className, count, icon, label, value, ...props },
    ref,
  ) {
    return (
      <button
        className={cn(
          'inline-flex h-9 items-center gap-2 rounded-md border border-tertiary bg-primary px-3 text-sm text-secondary transition-colors hover:bg-secondary hover:text-primary',
          className,
        )}
        ref={ref}
        type="button"
        {...props}
      >
        <span className="text-tertiary flex size-4 items-center justify-center">
          {icon}
        </span>
        <span className={cn(value && 'text-primary')}>{value ?? label}</span>
        {count !== undefined ? (
          <span className="bg-secondary text-tertiary ml-0.5 rounded px-1.5 text-[11px] tabular-nums">
            {count.toLocaleString()}
          </span>
        ) : null}
        <ChevronDown className="text-tertiary size-3.5" />
      </button>
    )
  },
)

interface FacetOption {
  count: number
  key: string
  label: string
}

export function OperationsLogToolbar({
  counts,
  entryTypes,
  environments,
  environmentSlugs,
  hideProjectFilter = false,
  hideTimeRange = false,
  onEntryTypes,
  onEnvironmentSlugs,
  onProjectSlugs,
  onRange,
  onView,
  projectNames,
  projectSlugs,
  range,
  view,
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
        count: counts.type[t] ?? 0,
        key: t,
        label: t,
      })),
    [availableEntryTypes, counts.type],
  )
  const environmentOptions: FacetOption[] = useMemo(
    () =>
      orderedEnvs.map((env) => ({
        count: counts.env[env.slug] ?? 0,
        key: env.slug,
        label: env.name,
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
      {hideTimeRange ? null : (
        <>
          <div
            aria-label="Time range"
            className="border-tertiary bg-secondary inline-flex items-center rounded-md border p-0.5"
            role="group"
          >
            {RANGES.map((r) => (
              <button
                className={cn(
                  'rounded px-2.5 py-1 text-xs font-medium transition-colors',
                  range === r.key
                    ? 'bg-primary text-primary shadow-sm'
                    : 'text-secondary hover:text-primary',
                )}
                key={r.key}
                onClick={() => onRange(r.key)}
                type="button"
              >
                {r.label}
              </button>
            ))}
          </div>

          <span aria-hidden className="bg-tertiary mx-1 h-6 w-px" />
        </>
      )}

      <FacetDropdown
        allLabel="All entry types"
        icon={<Filter className="size-3.5" />}
        label="Entry Type"
        onChange={(next) => onEntryTypes(next as OperationsLogEntryType[])}
        options={entryTypeOptions}
        selected={entryTypes}
      />

      <FacetDropdown
        allLabel="All environments"
        contentClassName="min-w-[220px]"
        icon={<Layers className="size-3.5" />}
        label="Environment"
        onChange={onEnvironmentSlugs}
        options={environmentOptions}
        selected={environmentSlugs}
      />

      {hideProjectFilter ? null : (
        <DropdownMenu
          onOpenChange={(open) => {
            if (!open) setProjectQuery('')
          }}
        >
          <DropdownMenuTrigger asChild>
            <TriggerButton
              count={
                projectSlugs.length > 0 ? undefined : projectEntries.length
              }
              icon={<Box className="size-3.5" />}
              label="Project"
              value={projectSlugs.length > 0 ? projectTriggerValue : undefined}
            />
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" className="min-w-65 p-0">
            <div className="border-tertiary relative border-b p-2">
              <Search className="text-tertiary pointer-events-none absolute top-1/2 left-4 size-3.5 -translate-y-1/2" />
              <Input
                autoFocus
                className="h-8 pl-7 text-sm"
                onChange={(e) => setProjectQuery(e.target.value)}
                placeholder="Filter projects…"
                value={projectQuery}
              />
            </div>
            <div className="max-h-72 overflow-y-auto py-1">
              <button
                className={cn(
                  'flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm transition-colors',
                  projectSlugs.length === 0 && 'bg-secondary text-primary',
                  projectSlugs.length > 0 &&
                    'text-secondary hover:bg-secondary',
                )}
                onClick={() => onProjectSlugs([])}
                type="button"
              >
                <Check
                  className={cn(
                    'size-3.5',
                    projectSlugs.length > 0 && 'invisible',
                  )}
                />
                All projects
              </button>
              {projectEntries.map(([slug, c]) => {
                const checked = projectSlugs.includes(slug)
                return (
                  <button
                    className={cn(
                      'flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm transition-colors',
                      checked && 'bg-secondary text-primary',
                      !checked && 'text-secondary hover:bg-secondary',
                    )}
                    key={slug}
                    onClick={() => onProjectSlugs(toggle(projectSlugs, slug))}
                    title={projectNames.get(slug) ?? slug}
                    type="button"
                  >
                    <Check
                      className={cn('size-3.5', !checked && 'invisible')}
                    />
                    <span className="flex-1 truncate font-mono text-[13px]">
                      {slug}
                    </span>
                    <span className="text-tertiary ml-3 text-xs">
                      {c.toLocaleString()}
                    </span>
                  </button>
                )
              })}
              {projectEntries.length === 0 ? (
                <div className="text-tertiary px-3 py-2 text-xs">
                  No projects match.
                </div>
              ) : null}
            </div>
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      <div
        aria-label="View"
        className="border-tertiary bg-secondary ml-auto inline-flex h-9 items-center rounded-md border p-1"
        role="group"
      >
        <button
          className={cn(
            'inline-flex h-full items-center gap-1.5 rounded px-3 text-xs font-medium transition-colors',
            view === 'stream'
              ? 'bg-primary text-primary shadow-sm'
              : 'text-secondary hover:text-primary',
          )}
          onClick={() => onView('stream')}
          type="button"
        >
          <List className="size-3.5" /> Stream
        </button>
        <button
          className={cn(
            'inline-flex h-full items-center gap-1.5 rounded px-3 text-xs font-medium transition-colors',
            view === 'grouped'
              ? 'bg-primary text-primary shadow-sm'
              : 'text-secondary hover:text-primary',
          )}
          onClick={() => onView('grouped')}
          type="button"
        >
          <GitBranch className="size-3.5" /> Releases
        </button>
      </div>
    </div>
  )
}

function FacetDropdown({
  allLabel,
  contentClassName,
  icon,
  label,
  onChange,
  options,
  selected,
}: {
  allLabel: string
  contentClassName?: string
  icon: React.ReactNode
  label: string
  onChange: (next: string[]) => void
  options: FacetOption[]
  selected: string[]
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
        className={contentClassName ?? 'min-w-50'}
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
            checked={selected.includes(o.key)}
            key={o.key}
            onSelect={(e) => {
              e.preventDefault()
              onChange(toggle(selected, o.key))
            }}
          >
            <span className="flex-1">{o.label}</span>
            <span className="text-tertiary ml-3 text-xs">
              {o.count.toLocaleString()}
            </span>
          </DropdownMenuCheckboxItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
