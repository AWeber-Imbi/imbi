import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Edit2 } from 'lucide-react'

import { getProjectTypeSchema } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import { PROJECT_TYPE_BASE_FIELDS_SET } from '@/lib/constants'
import { useIcon } from '@/lib/icons'
import { extractDynamicFields } from '@/lib/utils'
import type { ProjectType } from '@/types'

interface ProjectTypeDetailProps {
  onBack: () => void
  onEdit: () => void
  projectType: ProjectType
}

export function ProjectTypeDetail({
  onBack,
  onEdit,
  projectType,
}: ProjectTypeDetailProps) {
  const { data: ptSchema } = useQuery({
    queryFn: ({ signal }) => getProjectTypeSchema(signal),
    queryKey: ['projectTypeSchema'],
    staleTime: 5 * 60 * 1000,
  })

  const HeaderIcon = useIcon(projectType.icon ?? null, null)

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button onClick={onBack} variant="outline">
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Project Type info card */}
      <Card>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div>
            <div className="flex items-center gap-3">
              {projectType.icon && HeaderIcon ? (
                <HeaderIcon className="h-8 w-8" />
              ) : null}
              <CardTitle>{projectType.name}</CardTitle>
            </div>
            {projectType.description && (
              <p className="mt-1 text-sm text-secondary">
                {projectType.description}
              </p>
            )}
          </div>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            onClick={onEdit}
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Project Type
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div className="text-sm text-secondary">Slug</div>
              <div className="mt-1 text-primary">
                <code className="rounded bg-secondary px-2 py-1 text-sm text-primary">
                  {projectType.slug}
                </code>
              </div>
            </div>
            <div>
              <div className="text-sm text-secondary">Organization</div>
              <div className="mt-1 text-primary">
                {projectType.organization.name}
              </div>
            </div>
            {ptSchema && (
              <DynamicDetailFields
                data={extractDynamicFields(
                  projectType,
                  PROJECT_TYPE_BASE_FIELDS_SET,
                )}
                schema={ptSchema}
              />
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
