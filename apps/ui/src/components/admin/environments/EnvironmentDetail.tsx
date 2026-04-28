import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Edit2 } from 'lucide-react'

import { getEnvironmentSchema } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import { EntityIcon } from '@/components/ui/entity-icon'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import { extractDynamicFields } from '@/lib/utils'
import type { Environment } from '@/types'

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

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 h-4 w-4" />
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
                  className="h-8 w-8 rounded object-cover"
                  icon={environment.icon}
                />
              )}
              <CardTitle>{environment.name}</CardTitle>
            </div>
            {environment.description && (
              <p className="mt-1 text-sm text-secondary">
                {environment.description}
              </p>
            )}
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onEdit}
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Environment
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-sm text-secondary">Slug</div>
              <div className="mt-1 text-primary">
                <code className="rounded bg-secondary px-2 py-1 text-sm text-primary">
                  {environment.slug}
                </code>
              </div>
            </div>
            <div>
              <div className="text-sm text-secondary">Organization</div>
              <div className="mt-1 text-primary">
                {environment.organization.name}
              </div>
            </div>
            <div>
              <div className="text-sm text-secondary">Sort Order</div>
              <div className="mt-1 text-primary">
                {environment.sort_order ?? 0}
              </div>
            </div>
            <div>
              <div className="text-sm text-secondary">Label Color</div>
              <div className="mt-1 flex items-center gap-2">
                {environment.label_color ? (
                  <>
                    <div
                      className="h-6 w-6 rounded border"
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
    </div>
  )
}
