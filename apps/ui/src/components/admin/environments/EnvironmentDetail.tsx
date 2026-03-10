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

export function EnvironmentDetail({ environment, onEdit, onBack, isDarkMode }: EnvironmentDetailProps) {
  const { data: envSchema } = useQuery({
    queryKey: ['environmentSchema'],
    queryFn: getEnvironmentSchema,
    staleTime: 5 * 60 * 1000,
  })

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={onBack} className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <div>
            <div className="flex items-center gap-3">
              {environment.icon && (
                <img src={environment.icon} alt="" className="w-8 h-8 rounded object-cover" />
              )}
              <h2 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                {environment.name}
              </h2>
            </div>
            {environment.description && (
              <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                {environment.description}
              </p>
            )}
          </div>
        </div>
        <Button onClick={onEdit} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
          <Edit2 className="w-4 h-4 mr-2" />
          Edit Environment
        </Button>
      </div>

      {/* Environment Info */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`text-lg font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Environment Information
        </h3>
        <div className="grid grid-cols-2 gap-6">
          <div>
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Slug</div>
            <div className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              <code className={`px-2 py-1 rounded text-sm ${
                isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
              }`}>
                {environment.slug}
              </code>
            </div>
          </div>
          <div>
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Organization</div>
            <div className={`mt-1 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
              {environment.organization.name}
            </div>
          </div>
          <div>
            <div className={`text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>Label Color</div>
            <div className="mt-1 flex items-center gap-2">
              {environment.label_color ? (
                <>
                  <div
                    className="w-6 h-6 rounded border"
                    style={{ backgroundColor: environment.label_color }}
                  />
                  <span className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                    {environment.label_color}
                  </span>
                </>
              ) : (
                <span className={isDarkMode ? 'text-gray-500' : 'text-gray-400'}>
                  Not set
                </span>
              )}
            </div>
          </div>
          {envSchema && (
            <DynamicDetailFields
              schema={envSchema}
              data={extractDynamicFields(environment, ENVIRONMENT_BASE_FIELDS_SET)}
              isDarkMode={isDarkMode}
            />
          )}
        </div>
      </div>
    </div>
  )
}
