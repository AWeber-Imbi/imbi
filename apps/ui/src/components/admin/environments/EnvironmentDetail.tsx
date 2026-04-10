import { useQuery } from '@tanstack/react-query'
import { ArrowLeft, Edit2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { DynamicDetailFields } from '@/components/ui/dynamic-fields'
import { getEnvironmentSchema } from '@/api/endpoints'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import { extractDynamicFields } from '@/lib/utils'
import type { Environment } from '@/types'

interface EnvironmentDetailProps {
  environment: Environment
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function EnvironmentDetail({
  environment,
  onEdit,
  onBack,
  isDarkMode,
}: EnvironmentDetailProps) {
  const { data: envSchema } = useQuery({
    queryKey: ['environmentSchema'],
    queryFn: getEnvironmentSchema,
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

      {/* Environment info card */}
      <div
        className={`rounded-lg border ${isDarkMode ? 'border-gray-700 bg-gray-800' : 'border-gray-200 bg-white'}`}
      >
        {/* Title row */}
        <div
          className={`flex items-start justify-between border-b px-6 py-5 ${isDarkMode ? 'border-gray-700' : 'border-gray-200'}`}
        >
          <div>
            <div className="flex items-center gap-3">
              {environment.icon && (
                <img
                  src={environment.icon}
                  alt=""
                  className="h-8 w-8 rounded object-cover"
                />
              )}
              <h2
                className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                {environment.name}
              </h2>
            </div>
            {environment.description && (
              <p
                className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {environment.description}
              </p>
            )}
          </div>
          <Button
            onClick={onEdit}
            className="bg-amber-border text-white hover:bg-amber-border-strong"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Environment
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
                  {environment.slug}
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
                {environment.organization.name}
              </div>
            </div>
            <div>
              <div
                className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Sort Order
              </div>
              <div
                className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}
              >
                {environment.sort_order ?? 0}
              </div>
            </div>
            <div>
              <div
                className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Label Color
              </div>
              <div className="mt-1 flex items-center gap-2">
                {environment.label_color ? (
                  <>
                    <div
                      className="h-6 w-6 rounded border"
                      style={{ backgroundColor: environment.label_color }}
                    />
                    <span
                      className={isDarkMode ? 'text-white' : 'text-gray-900'}
                    >
                      {environment.label_color}
                    </span>
                  </>
                ) : (
                  <span
                    className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}
                  >
                    Not set
                  </span>
                )}
              </div>
            </div>
            {envSchema && (
              <DynamicDetailFields
                schema={envSchema}
                data={extractDynamicFields(
                  environment,
                  ENVIRONMENT_BASE_FIELDS_SET,
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
