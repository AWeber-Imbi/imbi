import { useMemo, useState } from 'react'

import { Link } from 'react-router-dom'

import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import { CheckCircle, ChevronRight, Clock, Rocket } from 'lucide-react'

import { getProjects, listOperationsLog } from '@/api/endpoints'
import type { OperationsLogPage } from '@/api/endpoints'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { Sk } from '@/components/ui/skeleton'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll'
import { useEnvironments } from '@/hooks/useOrgResources'
import { formatRelativeDate } from '@/lib/formatDate'
import type { OperationsLogRecord, Project } from '@/types'

const PAGE_SIZE = 20

// fallow-ignore-next-line complexity
export function RecentDeploymentsWidget() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const [envFilter, setEnvFilter] = useState<string | undefined>(undefined)
  const since = useMemo(
    () => new Date(Date.now() - 30 * 24 * 60 * 60 * 1000).toISOString(),
    [],
  )

  function handleEnvClick(slug: string) {
    setEnvFilter((prev) => (prev === slug ? undefined : slug))
  }

  const { data: environments } = useEnvironments(orgSlug)

  const { data: projects } = useQuery({
    enabled: Boolean(orgSlug),
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })

  const projectsBySlug = useMemo(() => {
    const map = new Map<string, Project>()
    for (const p of projects ?? []) map.set(p.slug, p)
    return map
  }, [projects])

  const {
    data,
    fetchNextPage,
    hasNextPage,
    isError,
    isFetchingNextPage,
    isLoading,
  } = useInfiniteQuery<
    OperationsLogPage,
    Error,
    InfiniteData<OperationsLogPage>,
    readonly unknown[],
    string | undefined
  >({
    enabled: Boolean(orgSlug),
    getNextPageParam: (lastPage) => lastPage.nextCursor,
    initialPageParam: undefined,
    queryFn: ({ pageParam, signal }) =>
      listOperationsLog(
        {
          cursor: pageParam,
          filters: {
            entry_type: 'Deployed',
            since,
            ...(envFilter ? { environment_slug: envFilter } : {}),
          },
          limit: PAGE_SIZE,
        },
        signal,
      ),
    queryKey: ['deployments-widget', orgSlug, envFilter, since],
    staleTime: 60_000,
  })

  const { sentinelRef } = useInfiniteScroll({
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
  })

  const items = useMemo(
    () => data?.pages.flatMap((p) => p.entries) ?? [],
    [data],
  )

  return (
    <Card className="flex h-150 flex-col p-6">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-primary text-lg">Recent Deployments</h3>
      </div>

      {(environments?.length ?? 0) > 0 && (
        <div className="mb-3 flex flex-wrap items-center gap-0.5">
          {environments!.map((env) => (
            <button
              className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
                envFilter === env.slug
                  ? 'bg-action text-action-foreground'
                  : 'text-secondary hover:text-primary'
              }`}
              key={env.slug}
              onClick={() => handleEnvClick(env.slug)}
              type="button"
            >
              {env.name}
            </button>
          ))}
        </div>
      )}

      <div aria-busy={isLoading} className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <DeploymentRowSkeleton key={i} />
            ))}
          </div>
        ) : isError ? (
          <div className="text-danger py-8 text-center text-sm">
            Unavailable
          </div>
        ) : items.length === 0 ? (
          <div className="text-secondary py-8 text-center text-sm">
            No recent deployments.
          </div>
        ) : (
          <div className="space-y-2">
            {items.map((d) => (
              <DeploymentRow
                deployment={d}
                key={d.id}
                projectsBySlug={projectsBySlug}
              />
            ))}
            <div ref={sentinelRef}>
              {isFetchingNextPage && <DeploymentRowSkeleton />}
            </div>
          </div>
        )}
      </div>
    </Card>
  )
}

// fallow-ignore-next-line complexity
function DeploymentRow({
  deployment: d,
  projectsBySlug,
}: {
  deployment: OperationsLogRecord
  projectsBySlug: Map<string, Project>
}) {
  const project = projectsBySlug.get(d.project_slug)
  const projectLabel = project
    ? `${project.team.slug}/${project.slug}`
    : d.project_slug
  const inProgress = d.completed_at == null
  const StatusIcon = inProgress ? Clock : CheckCircle
  const statusVariant: BadgeProps['variant'] = inProgress ? 'info' : 'success'
  const statusLabel = inProgress ? 'In Progress' : 'Success'
  const to = project
    ? `/projects/${project.id}`
    : `/operations-log?entry=${encodeURIComponent(d.id)}`

  return (
    <Link
      className="border-input bg-background hover:border-secondary block w-full rounded-lg border p-3 text-left transition-colors"
      to={to}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <Rocket className="text-tertiary mt-0.5 size-5 shrink-0" />
          <div className="min-w-0 flex-1">
            <div className="text-primary mb-1 truncate font-medium">
              {projectLabel}
            </div>
            <div className="mb-1 flex flex-wrap items-center gap-2">
              {d.version && (
                <code className="bg-secondary text-primary rounded px-2 py-0.5 text-xs">
                  {d.version}
                </code>
              )}
              <Badge
                className="rounded-full"
                variant={envVariant(d.environment_slug)}
              >
                {d.environment_slug}
              </Badge>
              <Badge className="gap-1 rounded-full" variant={statusVariant}>
                <StatusIcon className="size-3" />
                {statusLabel}
              </Badge>
            </div>
            <div className="text-tertiary text-xs">
              {d.performed_by ?? d.recorded_by} •{' '}
              {formatRelativeDate(d.occurred_at)}
            </div>
          </div>
        </div>
        <ChevronRight className="text-tertiary size-4 shrink-0" />
      </div>
    </Link>
  )
}

function DeploymentRowSkeleton() {
  return (
    <div className="border-input bg-background rounded-lg border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-3">
          <Sk circle h={20} w={20} />
          <div className="min-w-0 flex-1">
            <Sk className="mb-2" line w="55%" />
            <div className="mb-2 flex items-center gap-2">
              <Sk h={18} r={9999} w={56} />
              <Sk h={18} r={9999} w={72} />
            </div>
            <Sk line w="40%" />
          </div>
        </div>
        <Sk h={16} w={16} />
      </div>
    </div>
  )
}

// fallow-ignore-next-line complexity
function envVariant(slug: string): BadgeProps['variant'] {
  const s = slug.toLowerCase()
  if (s.includes('prod')) return 'accent'
  if (s.includes('stag')) return 'warning'
  if (s.includes('test') || s.includes('qa')) return 'info'
  return 'info'
}
