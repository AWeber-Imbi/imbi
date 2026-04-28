import { useMemo, useState } from 'react'

import { Search } from 'lucide-react'

import { Gravatar } from '@/components/ui/gravatar'
import { Input } from '@/components/ui/input'
import { useTheme } from '@/contexts/ThemeContext'
import { deriveChipColors } from '@/lib/chip-colors'
import { ENTRY_TYPE_ICONS } from '@/lib/ops-log-icons'
import { cn } from '@/lib/utils'
import { sortEnvironments } from '@/lib/utils'
import {
  type Environment,
  OPERATIONS_LOG_ENTRY_TYPES,
  type OperationsLogEntryType,
} from '@/types'

import type { TimeRange } from './opsLogHelpers'
import { cleanName } from './opsLogHelpers'

export interface SidebarCounts {
  env: Record<string, number>
  person: Record<string, number>
  project: Record<string, number>
  type: Partial<Record<OperationsLogEntryType, number>>
}

interface SidebarProps {
  counts: SidebarCounts
  entryType?: OperationsLogEntryType
  environments: Environment[]
  environmentSlug: string | undefined
  onEntryType: (t: OperationsLogEntryType | undefined) => void
  onEnvironment: (slug: string | undefined) => void
  onPerformer: (email: string | undefined) => void
  onProject: (slug: string | undefined) => void
  onRange: (r: TimeRange) => void
  performer: string | undefined
  performerDisplayNames: Map<string, string>
  projectNames: Map<string, string>
  projectSlug: string | undefined
  range: TimeRange
}

const RANGES: { key: TimeRange; label: string }[] = [
  { key: '24h', label: '24h' },
  { key: '7d', label: '7d' },
  { key: '30d', label: '30d' },
  { key: '90d', label: '90d' },
  { key: 'all', label: 'All' },
]

export function OperationsLogSidebar({
  counts,
  entryType,
  environments,
  environmentSlug,
  onEntryType,
  onEnvironment,
  onPerformer,
  onProject,
  onRange,
  performer,
  performerDisplayNames,
  projectNames,
  projectSlug,
  range,
}: SidebarProps) {
  const { isDarkMode } = useTheme()
  const [projectFilter, setProjectFilter] = useState('')
  const projectEntries = useMemo(
    () =>
      Object.entries(counts.project).sort(
        (a, b) =>
          b[1] - a[1] ||
          (projectNames.get(a[0]) ?? a[0]).localeCompare(
            projectNames.get(b[0]) ?? b[0],
          ),
      ),
    [counts.project, projectNames],
  )
  const filteredProjects = useMemo(() => {
    const q = projectFilter.toLowerCase().trim()
    if (!q) return projectEntries
    return projectEntries.filter(([slug]) => {
      const name = (projectNames.get(slug) ?? slug).toLowerCase()
      return slug.toLowerCase().includes(q) || name.includes(q)
    })
  }, [projectEntries, projectFilter, projectNames])

  const topPeople = Object.entries(counts.person)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)

  const orderedEnvironments = sortEnvironments(environments).filter(
    (env) => (counts.env[env.slug] ?? 0) > 0 || environmentSlug === env.slug,
  )

  return (
    <aside className="sticky top-20 flex flex-col gap-5 self-start text-sm">
      <Section title="Time range">
        <div
          aria-label="Time range"
          className="mx-2 flex items-center rounded-md border border-tertiary bg-secondary p-0.5"
          role="group"
        >
          {RANGES.map((r) => (
            <button
              className={cn(
                'flex-1 rounded px-2 py-1 text-xs font-medium transition-colors',
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
      </Section>

      <Section title="Event type">
        {OPERATIONS_LOG_ENTRY_TYPES.filter(
          (t) => (counts.type[t] ?? 0) > 0,
        ).map((t) => {
          const Icon = ENTRY_TYPE_ICONS[t]
          return (
            <SideButton
              active={entryType === t}
              count={counts.type[t]}
              icon={<Icon className="h-3.5 w-3.5" />}
              key={t}
              onClick={() => onEntryType(entryType === t ? undefined : t)}
            >
              {t}
            </SideButton>
          )
        })}
      </Section>

      {orderedEnvironments.length > 0 && (
        <Section title="Environment">
          {orderedEnvironments.map((env) => {
            const colors = env.label_color
              ? deriveChipColors(env.label_color, isDarkMode)
              : null
            return (
              <SideButton
                active={environmentSlug === env.slug}
                count={counts.env[env.slug] ?? 0}
                icon={
                  <span
                    aria-hidden
                    className="h-2 w-2 rounded-full"
                    style={{
                      backgroundColor: colors?.border ?? 'currentColor',
                    }}
                  />
                }
                key={env.slug}
                onClick={() =>
                  onEnvironment(
                    environmentSlug === env.slug ? undefined : env.slug,
                  )
                }
              >
                {env.name}
              </SideButton>
            )
          })}
        </Section>
      )}

      {projectEntries.length > 0 && (
        <Section
          rightMeta={
            <span className="text-xs font-normal tracking-normal text-tertiary">
              {projectEntries.length}
            </span>
          }
          title="Projects"
        >
          <div className="relative mx-2 mb-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-tertiary" />
            <Input
              className="h-8 pl-8 text-sm"
              onChange={(e) => setProjectFilter(e.target.value)}
              placeholder="Filter projects…"
              value={projectFilter}
            />
          </div>
          {filteredProjects.map(([slug, c]) => (
            <SideButton
              active={projectSlug === slug}
              count={c}
              key={slug}
              onClick={() => onProject(projectSlug === slug ? undefined : slug)}
              title={projectNames.get(slug) ?? slug}
            >
              <span className="font-mono text-[13px]">{slug}</span>
            </SideButton>
          ))}
        </Section>
      )}

      {topPeople.length > 0 && (
        <Section title="People">
          {topPeople.map(([email, c]) => (
            <SideButton
              active={performer === email}
              count={c}
              icon={
                <Gravatar
                  className="h-4 w-4 rounded-full"
                  email={email}
                  size={18}
                />
              }
              key={email}
              onClick={() =>
                onPerformer(performer === email ? undefined : email)
              }
            >
              {performerDisplayNames.get(email) ?? cleanName(email)}
            </SideButton>
          ))}
        </Section>
      )}
    </aside>
  )
}

function Section({
  children,
  rightMeta,
  title,
}: {
  children: React.ReactNode
  rightMeta?: React.ReactNode
  title: string
}) {
  return (
    <div className="flex flex-col gap-1">
      <h3 className="mx-2 mb-1 flex items-center justify-between text-overline uppercase tracking-[0.06em] text-tertiary">
        <span>{title}</span>
        {rightMeta}
      </h3>
      {children}
    </div>
  )
}

function SideButton({
  active,
  children,
  count,
  icon,
  onClick,
  title,
}: {
  active?: boolean
  children: React.ReactNode
  count?: number
  icon?: React.ReactNode
  onClick: () => void
  title?: string
}) {
  return (
    <button
      className={cn(
        'flex w-full items-center gap-2.5 rounded-md px-2 py-1.5 text-left text-sm transition-colors',
        'hover:bg-secondary',
        active ? 'bg-secondary font-medium text-primary' : 'text-secondary',
      )}
      onClick={onClick}
      title={title}
      type="button"
    >
      {icon ? (
        <span className="flex h-4 w-4 flex-shrink-0 items-center justify-center text-tertiary">
          {icon}
        </span>
      ) : null}
      <span className="min-w-0 flex-1 truncate">{children}</span>
      {count != null ? (
        <span className="text-xs text-tertiary">{count}</span>
      ) : null}
    </button>
  )
}
