import { useMemo } from 'react'

import { useQuery } from '@tanstack/react-query'
import { CheckCircle, ChevronRight, Clock, Rocket } from 'lucide-react'

import { getProjects } from '@/api/endpoints'
import { Badge, type BadgeProps } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useRecentDeployments } from '@/hooks/useRecentDeployments'
import { formatRelativeDate } from '@/lib/formatDate'
import type { Project } from '@/types'

interface RecentDeploymentsWidgetProps {
  onProjectSelect?: (projectId: string) => void
}

export function RecentDeploymentsWidget({
  onProjectSelect,
}: RecentDeploymentsWidgetProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''

  const { data: deployments, isLoading } = useRecentDeployments(orgSlug, 10)
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

  const items = (deployments ?? []).slice(0, 5)

  return (
    <Card className="p-6">
      <div className="mb-4 flex items-center justify-between">
        <h3 className="text-lg text-primary">Recent Deployments</h3>
      </div>

      {isLoading ? (
        <div className="py-8 text-center text-sm text-secondary">
          Loading deployments…
        </div>
      ) : items.length === 0 ? (
        <div className="py-8 text-center text-sm text-secondary">
          No recent deployments.
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((d) => {
            const project = projectsBySlug.get(d.project_slug)
            const projectLabel = project
              ? `${project.team.slug}/${project.slug}`
              : d.project_slug
            const inProgress = d.completed_at == null
            const StatusIcon = inProgress ? Clock : CheckCircle
            const statusVariant: BadgeProps['variant'] = inProgress
              ? 'info'
              : 'success'
            const statusLabel = inProgress ? 'In Progress' : 'Success'

            return (
              <button
                className="w-full rounded-lg border border-input bg-background p-3 text-left transition-colors hover:border-secondary"
                key={d.id}
                onClick={() => onProjectSelect?.(d.project_id)}
                type="button"
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex min-w-0 flex-1 items-start gap-3">
                    <Rocket className="mt-0.5 h-5 w-5 flex-shrink-0 text-tertiary" />
                    <div className="min-w-0 flex-1">
                      <div className="mb-1 truncate font-medium text-primary">
                        {projectLabel}
                      </div>
                      <div className="mb-1 flex flex-wrap items-center gap-2">
                        {d.version && (
                          <code className="rounded bg-secondary px-2 py-0.5 text-xs text-primary">
                            {d.version}
                          </code>
                        )}
                        <Badge
                          className="rounded-full"
                          variant={envVariant(d.environment_slug)}
                        >
                          {d.environment_slug}
                        </Badge>
                        <Badge
                          className="gap-1 rounded-full"
                          variant={statusVariant}
                        >
                          <StatusIcon className="h-3 w-3" />
                          {statusLabel}
                        </Badge>
                      </div>
                      <div className="text-xs text-gray-500">
                        {d.performed_by ?? d.recorded_by} •{' '}
                        {formatRelativeDate(d.occurred_at)}
                      </div>
                    </div>
                  </div>
                  <ChevronRight className="h-4 w-4 flex-shrink-0 text-tertiary" />
                </div>
              </button>
            )
          })}
        </div>
      )}
    </Card>
  )
}

function envVariant(slug: string): BadgeProps['variant'] {
  const s = slug.toLowerCase()
  if (s.includes('prod')) return 'accent'
  if (s.includes('stag')) return 'warning'
  if (s.includes('test') || s.includes('qa')) return 'info'
  return 'info'
}
