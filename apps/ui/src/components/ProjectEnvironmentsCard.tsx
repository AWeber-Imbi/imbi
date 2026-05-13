import { ExternalLink } from 'lucide-react'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { sanitizeHttpUrl } from '@/lib/utils'
import type { Project } from '@/types'

type Environment = NonNullable<Project['environments']>[number]

interface ProjectEnvironmentsCardProps {
  deploymentStatus: Record<
    string,
    { status: string; updated: string; version: string }
  >
  environments: Environment[]
}

export function ProjectEnvironmentsCard({
  deploymentStatus,
  environments,
}: ProjectEnvironmentsCardProps) {
  const muted = 'text-tertiary'
  const divider = 'border-tertiary'

  return (
    <Card>
      <CardHeader>
        <CardTitle>Environments</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-0">
          {environments.map((env) => {
            const url =
              typeof env.url === 'string' ? sanitizeHttpUrl(env.url) : null
            const deployment = deploymentStatus[env.slug]
            return (
              <div
                className={`flex items-center border-b py-2 ${divider} last:border-0`}
                key={env.slug}
              >
                <div className="w-32 shrink-0">
                  <EnvironmentBadge
                    label_color={env.label_color}
                    name={env.name}
                    slug={env.slug}
                  />
                </div>
                <div className="w-28 shrink-0 text-right">
                  <span className="text-tertiary font-mono text-sm">
                    {deployment?.version ?? ''}
                  </span>
                </div>
                <div className="flex-1 text-right">
                  {url ? (
                    <a
                      className={
                        'text-warning inline-flex items-center gap-1.5 text-sm whitespace-nowrap hover:underline'
                      }
                      href={url}
                      rel="noopener noreferrer"
                      target="_blank"
                    >
                      {url}
                      <ExternalLink className="text-warning size-3" />
                    </a>
                  ) : (
                    <span className={`text-sm ${muted}`}>&mdash;</span>
                  )}
                </div>
              </div>
            )
          })}
        </div>
      </CardContent>
    </Card>
  )
}
