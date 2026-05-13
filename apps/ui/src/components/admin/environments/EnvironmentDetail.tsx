import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Edit2 } from 'lucide-react'

import { getAdminPlugins, getEnvironmentSchema } from '@/api/endpoints'
import { AnchorEdgesCard } from '@/components/admin/AnchorEdgesCard'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import { EntityIcon } from '@/components/ui/entity-icon'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import { queryKeys } from '@/lib/queryKeys'
import { extractDynamicFields } from '@/lib/utils'
import type { Environment, InstalledPlugin } from '@/types'

interface EnvironmentDetailProps {
  environment: Environment
  onBack: () => void
  onEdit: () => void
}

export function EnvironmentDetail({
  environment,
  onBack,
  onEdit,
}: EnvironmentDetailProps) {
  const { data: envSchema } = useQuery({
    queryFn: ({ signal }) => getEnvironmentSchema(signal),
    queryKey: ['environmentSchema'],
    staleTime: 5 * 60 * 1000,
  })
  const { data: pluginsResponse } = useQuery({
    queryFn: ({ signal }) => getAdminPlugins(signal),
    queryKey: queryKeys.adminPlugins(),
    staleTime: 60 * 1000,
  })

  const enabledPlugins: InstalledPlugin[] = (
    pluginsResponse?.installed ?? []
  ).filter((p) => p.enabled)
  const environmentEdges = enabledPlugins.flatMap((plugin) =>
    (plugin.edge_labels ?? [])
      .filter((edge) => edge.from_labels.includes('Environment'))
      .map((edge) => ({ edge, plugin })),
  )

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 size-4" />
          Back
        </Button>
      </div>

      {/* Environment info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div>
            <div className="flex items-center gap-3">
              {environment.icon && (
                <EntityIcon
                  className="size-8 rounded object-cover"
                  icon={environment.icon}
                />
              )}
              <CardTitle>{environment.name}</CardTitle>
            </div>
            {environment.description && (
              <p className="text-secondary mt-1 text-sm">
                {environment.description}
              </p>
            )}
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onEdit}
          >
            <Edit2 className="mr-2 size-4" />
            Edit Environment
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-secondary text-sm">Slug</div>
              <div className="text-primary mt-1">
                <code className="bg-secondary text-primary rounded px-2 py-1 text-sm">
                  {environment.slug}
                </code>
              </div>
            </div>
            <div>
              <div className="text-secondary text-sm">Organization</div>
              <div className="text-primary mt-1">
                {environment.organization.name}
              </div>
            </div>
            <div>
              <div className="text-secondary text-sm">Sort Order</div>
              <div className="text-primary mt-1">
                {environment.sort_order ?? 0}
              </div>
            </div>
            <div>
              <div className="text-secondary text-sm">Label Color</div>
              <div className="mt-1 flex items-center gap-2">
                {environment.label_color ? (
                  <>
                    <div
                      className="size-6 rounded border"
                      style={{ backgroundColor: environment.label_color }}
                    />
                    <span className="text-primary">
                      {environment.label_color}
                    </span>
                  </>
                ) : (
                  <span className="text-tertiary">Not set</span>
                )}
              </div>
            </div>
            {envSchema && (
              <DynamicDetailFields
                data={extractDynamicFields(
                  environment,
                  ENVIRONMENT_BASE_FIELDS_SET,
                )}
                schema={envSchema}
              />
            )}
          </div>
        </CardContent>
      </Card>

      {environmentEdges.map(({ edge, plugin }) => (
        <AnchorEdgesCard
          anchor={{
            orgSlug: environment.organization.slug,
            slug: environment.slug,
          }}
          anchorKind="environment"
          edge={edge}
          entityPluginSlug={plugin.slug}
          key={`${plugin.slug}:${edge.name}`}
          manifest={plugin}
          title={`${plugin.name}: ${edge.name}`}
        />
      ))}
    </div>
  )
}
