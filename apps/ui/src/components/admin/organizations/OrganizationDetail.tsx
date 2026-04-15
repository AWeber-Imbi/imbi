import { ArrowLeft, Edit2, Building2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EntityIcon } from '@/components/ui/entity-icon'
import { formatDate } from '@/lib/formatDate'
import type { Organization } from '@/types'

interface OrganizationDetailProps {
  organization: Organization
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function OrganizationDetail({
  organization,
  onEdit,
  onBack,
  isDarkMode,
}: OrganizationDetailProps) {
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

      {/* Organization info card */}
      <Card className={isDarkMode ? 'border-gray-700 bg-gray-800' : ''}>
        <CardHeader className="flex flex-row items-start justify-between space-y-0 border-b px-6 py-5">
          <div className="flex items-center gap-3">
            {organization.icon ? (
              <EntityIcon
                icon={organization.icon}
                className="h-8 w-8 rounded object-cover"
              />
            ) : (
              <Building2
                className={`h-6 w-6 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              />
            )}
            <div>
              <CardTitle>{organization.name}</CardTitle>
              <p
                className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                {organization.description || 'No description provided'}
              </p>
            </div>
          </div>
          <Button
            onClick={onEdit}
            className="bg-amber-border text-white hover:bg-amber-border-strong"
          >
            <Edit2 className="mr-2 h-4 w-4" />
            Edit Organization
          </Button>
        </CardHeader>

        <CardContent className="p-6">
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <div>
              <div
                className={`mb-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Slug
              </div>
              <code
                className={`rounded px-2 py-1 text-sm ${
                  isDarkMode
                    ? 'bg-gray-700 text-gray-300'
                    : 'bg-gray-100 text-gray-700'
                }`}
              >
                {organization.slug}
              </code>
            </div>

            <div>
              <div
                className={`mb-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
              >
                Created
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {formatDate(organization.created_at)}
              </div>
            </div>

            {organization.updated_at && (
              <div>
                <div
                  className={`mb-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}
                >
                  Last Modified
                </div>
                <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                  {formatDate(organization.updated_at)}
                </div>
              </div>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  )
}
