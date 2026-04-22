import { ExternalLink } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { sanitizeHttpUrl } from '@/lib/utils'
import type { Project } from '@/types'

type Environment = NonNullable<Project['environments']>[number]

interface ProjectEnvironmentsCardProps {
  environments: Environment[]
  deploymentStatus: Record<
    string,
    { version: string; status: string; updated: string }
  >
}

export function ProjectEnvironmentsCard({
  environments,
  deploymentStatus,
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
                key={env.slug}
                className={`flex items-center border-b py-2 ${divider} last:border-0`}
              >
                <div className="w-32 flex-shrink-0">
                  <EnvironmentBadge
                    name={env.name}
                    slug={env.slug}
                    label_color={env.label_color}
                  />
                </div>
                <div className="flex-1 text-center">
                  <span className="font-mono text-sm text-tertiary">
                    {deployment?.version ?? ''}
                  </span>
                </div>
                <div className="flex-1 text-right">
                  {url ? (
                    <a
                      href={url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className={
                        'inline-flex items-center gap-1.5 text-sm text-warning hover:underline'
                      }
                    >
                      {url}
                      <ExternalLink className="h-3 w-3 text-warning" />
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
