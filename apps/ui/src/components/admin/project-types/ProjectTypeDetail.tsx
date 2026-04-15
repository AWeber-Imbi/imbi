import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Edit2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import { getProjectTypeSchema } from '@/api/endpoints'
import { PROJECT_TYPE_BASE_FIELDS_SET } from '@/lib/constants'
import { getIcon } from '@/lib/icons'
import { extractDynamicFields } from '@/lib/utils'
import type { ProjectType } from '@/types'

interface ProjectTypeDetailProps {
  projectType: ProjectType
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function ProjectTypeDetail({
  projectType,
  onEdit,
  onBack,
  isDarkMode,
}: ProjectTypeDetailProps) {
  const { data: ptSchema } = useQuery({
    queryKey: ['projectTypeSchema'],
    queryFn: getProjectTypeSchema,
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="space-y-6">
      {/* Back button */}
      <div>
        <Button
          variant="outline"
          onClick={onBack}
          className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
        >
          <ArrowLeft className="mr-2 h-4 w-4" />
          Back
        </Button>
      </div>

      {/* Project Type info card */}
      <Card className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div>
            <div className="flex items-center gap-3">
              {projectType.icon &&
                (projectType.icon.startsWith('/uploads/') ? (
                  <img
                    src={projectType.icon}
                    alt=""
                    className="h-8 w-8 rounded object-cover"
                  />
                ) : (
                  (() => {
                    const Icon = getIcon(projectType.icon, null)
                    return Icon ? <Icon className="h-8 w-8" /> : null
                  })()
                ))}
              <CardTitle>{projectType.name}</CardTitle>
            </div>
            {projectType.description && (
              <p
                className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {projectType.description}
              </p>
            )}
          </div>
          <Button
            onClick={onEdit}
            className="bg-amber-border text-white hover:bg-amber-border-strong"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Project Type
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6">
            <div>
              <div
                className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Slug
              </div>
              <div
                className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                <code
                  className={`rounded px-2 py-1 text-sm ${
                    isDarkMode
                      ? 'bg-gray-700 text-gray-300'
                      : 'bg-gray-100 text-gray-700'
                  }`}
                >
                  {projectType.slug}
                </code>
              </div>
            </div>
            <div>
              <div
                className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Organization
              </div>
              <div
                className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                {projectType.organization.name}
              </div>
            </div>
            {ptSchema && (
              <DynamicDetailFields
                schema={ptSchema}
                data={extractDynamicFields(
                  projectType,
                  PROJECT_TYPE_BASE_FIELDS_SET,
                )}
                isDarkMode={isDarkMode}
              />
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
