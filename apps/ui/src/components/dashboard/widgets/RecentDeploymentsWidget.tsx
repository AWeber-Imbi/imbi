import { useMemo, useState } from 'react'

import { useNavigate } from 'react-router-dom'

import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import type { InfiniteData } from '@tanstack/react-query'
import { CheckCircle, ChevronRight, Clock, Rocket } from 'lucide-react'

import {
  getProjects,
  listEnvironments,
  listOperationsLog,
} from '@/api/endpoints'
import type { OperationsLogPage } from '@/api/endpoints'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useInfiniteScroll } from '@/hooks/useInfiniteScroll'
import { formatRelativeDate } from '@/lib/formatDate'
import type { OperationsLogRecord, Project } from '@/types'

const PAGE_SIZE = 20

// fallow-ignore-next-line complexity
export function RecentDeploymentsWidget() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const [envFilter, setEnvFilter] = useState<string | undefined>(undefined)

  function handleEnvClick(slug: string) {
    setEnvFilter((prev) => (prev === slug ? undefined : slug))
  }

  const { data: environments } = useQuery({
    enabled: Boolean(orgSlug),
    queryFn: ({ signal }) => listEnvironments(orgSlug, signal),
    queryKey: ['environments', orgSlug],
    staleTime: 5 * 60_000,
  })

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

  const { data, fetchNextPage, hasNextPage, isFetchingNextPage, isLoading } =
    useInfiniteQuery<
      OperationsLogPage,
      Error,
      InfiniteData<OperationsLogPage>,
      readonly unknown[],
      string | undefined
    >({
      enabled: Boolean(orgSlug),
      getNextPageParam: (lastPage) => lastPage.nextCursor,
      initialPageParam: undefined,
      queryFn: ({ pageParam, signal }) => {
        const since = new Date(
          Date.now() - 30 * 24 * 60 * 60 * 1000,
        ).toISOString()
        return listOperationsLog(
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
        )
      },
      queryKey: ['deployments-widget', orgSlug, envFilter],
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

      <div className="min-h-0 flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="space-y-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <div
                aria-hidden="true"
                className="bg-tertiary/30 h-16 animate-pulse rounded-lg"
                key={i}
              />
            ))}
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
              {isFetchingNextPage && (
                <div
                  aria-hidden="true"
                  className="bg-tertiary/30 h-16 animate-pulse rounded-lg"
                />
              )}
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
  const navigate = useNavigate()
  const project = projectsBySlug.get(d.project_slug)
  const projectLabel = project
    ? `${project.team.slug}/${project.slug}`
    : d.project_slug
  const inProgress = d.completed_at == null
  const StatusIcon = inProgress ? Clock : CheckCircle
  const statusVariant: BadgeProps['variant'] = inProgress ? 'info' : 'success'
  const statusLabel = inProgress ? 'In Progress' : 'Success'

  return (
    <button
      className="border-input bg-background hover:border-secondary w-full rounded-lg border p-3 text-left transition-colors"
      onClick={() =>
        navigate(`/operations-log?entry=${encodeURIComponent(d.id)}`)
      }
      type="button"
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
    </button>
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
