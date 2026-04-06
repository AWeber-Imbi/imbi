import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Edit2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import { getProjectTypeSchema } from '@/api/endpoints'
import { PROJECT_TYPE_BASE_FIELDS_SET } from '@/lib/constants'
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
      <div
        className={`rounded-lg border ${isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'}`}
      >
        {/* Title row */}
        <div
          className={`flex items-start justify-between border-b px-6 py-5 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <div>
            <div className="flex items-center gap-3">
              {projectType.icon && (
                <img
                  src={projectType.icon}
                  alt=""
                  className="rounded h-8 w-8 object-cover"
                />
              )}
              <h2
                className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                {projectType.name}
              </h2>
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
            className="bg-[#2A4DD0] text-white hover:bg-blue-700"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Project Type
          </Button>
        </div>

        {/* Info section */}
        <div className="p-6">
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
        </div>
      </div>
    </div>
  )
}
