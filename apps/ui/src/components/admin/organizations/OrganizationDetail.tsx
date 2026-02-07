import { ArrowLeft, Edit2, Building2 } from 'lucide-react'
import { Button } from '../../ui/button'
import type { Organization } from '@/types'

interface OrganizationDetailProps {
  organization: Organization
  onEdit: () => void
  onBack: () => void
  isDarkMode: boolean
}

export function OrganizationDetail({ organization, onEdit, onBack, isDarkMode }: OrganizationDetailProps) {
  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleDateString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    })
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Button variant="outline" onClick={onBack} className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}>
            <ArrowLeft className="w-4 h-4 mr-2" />
            Back
          </Button>
          <div className="flex items-center gap-3">
            {organization.icon_url ? (
              <img src={organization.icon_url} alt="" className="w-8 h-8 rounded object-cover" />
            ) : (
              <Building2 className={`w-6 h-6 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`} />
            )}
            <div>
              <h2 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
                {organization.name}
              </h2>
              <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                {organization.description || 'No description provided'}
              </p>
            </div>
          </div>
        </div>
        <Button onClick={onEdit} className="bg-[#2A4DD0] hover:bg-blue-700 text-white">
          <Edit2 className="w-4 h-4 mr-2" />
          Edit Organization
        </Button>
      </div>

      {/* Organization Info */}
      <div className={`p-6 rounded-lg border ${
        isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
      }`}>
        <h3 className={`text-lg font-semibold mb-4 ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
          Organization Information
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
          <div>
            <div className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              Slug
            </div>
            <code className={`px-2 py-1 rounded text-sm ${
              isDarkMode ? 'bg-gray-700 text-gray-300' : 'bg-gray-100 text-gray-700'
            }`}>
              {organization.slug}
            </code>
          </div>

          <div>
            <div className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
              Created
            </div>
            <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
              {formatDate(organization.created_at)}
            </div>
          </div>

          {organization.last_modified_at && (
            <div>
              <div className={`text-sm mb-1 ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
                Last Modified
              </div>
              <div className={isDarkMode ? 'text-white' : 'text-gray-900'}>
                {formatDate(organization.last_modified_at)}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
