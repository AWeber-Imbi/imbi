import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { IconUpload } from '@/components/ui/icon-upload'
import { KeyValueEditor } from '@/components/ui/key-value-editor'
import { useOrganization } from '@/contexts/OrganizationContext'
import { listTeams } from '@/api/endpoints'
import { slugify } from '@/lib/utils'
import type { Team, ThirdPartyService, ThirdPartyServiceCreate } from '@/types'

interface ThirdPartyServiceFormProps {
  service: ThirdPartyService | null
  onSave: (svc: ThirdPartyServiceCreate) => void
  onCancel: () => void
  isDarkMode: boolean
  isLoading?: boolean
  error?: any
}

const STATUS_OPTIONS = [
  { value: 'active', label: 'Active' },
  { value: 'evaluating', label: 'Evaluating' },
  { value: 'deprecated', label: 'Deprecated' },
  { value: 'inactive', label: 'Inactive' },
]

export function ThirdPartyServiceForm({
  service,
  onSave,
  onCancel,
  isDarkMode,
  isLoading = false,
  error,
}: ThirdPartyServiceFormProps) {
  const isEditing = !!service
  const { selectedOrganization, organizations } = useOrganization()

  const [name, setName] = useState(service?.name || '')
  const [slug, setSlug] = useState(service?.slug || '')
  const [description, setDescription] = useState(service?.description || '')
  const [icon, setIcon] = useState(service?.icon || '')
  const [vendor, setVendor] = useState(service?.vendor || '')
  const [serviceUrl, setServiceUrl] = useState(service?.service_url || '')
  const [category, setCategory] = useState(service?.category || '')
  const [status, setStatus] = useState<string>(service?.status || 'active')
  const [links, setLinks] = useState<Record<string, string | number>>(service?.links || {})
  const [identifiers, setIdentifiers] = useState<Record<string, string | number>>(service?.identifiers || {})
  const [orgSlug, setOrgSlug] = useState(
    service?.organization.slug || selectedOrganization?.slug || ''
  )
  const [teamSlug, setTeamSlug] = useState(service?.team?.slug || '')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: teams = [] } = useQuery({
    queryKey: ['teams', orgSlug],
    queryFn: () => listTeams(orgSlug),
    enabled: !!orgSlug,
  })

  const orgTeams = teams.filter((t: Team) => t.organization.slug === orgSlug)

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Service name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9_-]+$/.test(slug)) {
      newErrors.slug = 'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (!orgSlug) newErrors.organization = 'Organization is required'
    if (!vendor.trim()) newErrors.vendor = 'Vendor is required'
    if (serviceUrl && !/^https?:\/\/.+/.test(serviceUrl)) {
      newErrors.service_url = 'Must be a valid URL starting with http:// or https://'
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    onSave({
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || null,
      icon: icon.trim() || null,
      vendor: vendor.trim(),
      service_url: serviceUrl.trim() || null,
      category: category.trim() || null,
      status,
      links: links as Record<string, string>,
      identifiers,
      organization_slug: orgSlug,
      team_slug: teamSlug || null,
    })
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(slugify(value))
    }
  }

  const selectClass = `w-full px-3 py-2 rounded-lg border text-sm ${
    isDarkMode
      ? 'bg-gray-700 border-gray-600 text-white'
      : 'bg-white border-gray-300 text-gray-900'
  }`

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className={`text-2xl font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            {isEditing ? 'Edit Third-Party Service' : 'Add Third-Party Service'}
          </h2>
          <p className={`mt-1 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            {isEditing ? 'Update service information' : 'Register a new external SaaS or managed service'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={isLoading}
            className={isDarkMode ? 'border-gray-600 text-gray-300' : ''}
          >
            <X className="w-4 h-4 mr-2" />
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isLoading}
            className="bg-[#2A4DD0] hover:bg-blue-700 text-white"
          >
            <Save className="w-4 h-4 mr-2" />
            {isLoading ? 'Saving...' : isEditing ? 'Save Changes' : 'Create Service'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {error && (
        <div className={`rounded-lg border p-4 ${
          isDarkMode ? 'bg-red-900/20 border-red-700' : 'bg-red-50 border-red-200'
        }`}>
          <div className="flex items-start gap-3">
            <AlertCircle className={`w-5 h-5 flex-shrink-0 ${isDarkMode ? 'text-red-400' : 'text-red-600'}`} />
            <div>
              <div className={`font-medium ${isDarkMode ? 'text-red-400' : 'text-red-800'}`}>
                Failed to save service
              </div>
              <div className={`text-sm mt-1 ${isDarkMode ? 'text-red-300' : 'text-red-700'}`}>
                {error?.response?.data?.detail || error?.message || 'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        {/* Basic Information */}
        <div className={`p-6 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Service Information
          </h3>

          <div className="space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Organization <span className="text-red-500">*</span>
                </label>
                <select
                  value={orgSlug}
                  onChange={(e) => {
                    setOrgSlug(e.target.value)
                    setTeamSlug('')
                  }}
                  disabled={isEditing || isLoading}
                  className={`${selectClass} ${isEditing ? 'opacity-60 cursor-not-allowed' : ''} ${
                    errors.organization ? 'border-red-500' : ''
                  }`}
                >
                  <option value="">Select organization...</option>
                  {organizations.map((org) => (
                    <option key={org.slug} value={org.slug}>{org.name}</option>
                  ))}
                </select>
                {errors.organization && (
                  <div className={`flex items-center gap-1 mt-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}>
                    <AlertCircle className="w-3 h-3" />
                    {errors.organization}
                  </div>
                )}
              </div>

              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Managing Team
                </label>
                <select
                  value={teamSlug}
                  onChange={(e) => setTeamSlug(e.target.value)}
                  disabled={isLoading || !orgSlug}
                  className={selectClass}
                >
                  <option value="">No team assigned</option>
                  {orgTeams.map((team) => (
                    <option key={team.slug} value={team.slug}>{team.name}</option>
                  ))}
                </select>
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Service Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Stripe"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                    errors.name ? 'border-red-500' : ''
                  }`}
                />
                {errors.name && (
                  <div className={`flex items-center gap-1 mt-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}>
                    <AlertCircle className="w-3 h-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Slug <span className="text-red-500">*</span>
                </label>
                <Input
                  value={slug}
                  onChange={(e) => setSlug(e.target.value)}
                  placeholder="e.g., stripe"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                    errors.slug ? 'border-red-500' : ''
                  }`}
                />
                {errors.slug && (
                  <div className={`flex items-center gap-1 mt-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}>
                    <AlertCircle className="w-3 h-3" />
                    {errors.slug}
                  </div>
                )}
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Vendor <span className="text-red-500">*</span>
                </label>
                <Input
                  value={vendor}
                  onChange={(e) => setVendor(e.target.value)}
                  placeholder="e.g., Stripe, Inc."
                  disabled={isLoading}
                  className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                    errors.vendor ? 'border-red-500' : ''
                  }`}
                />
                {errors.vendor && (
                  <div className={`flex items-center gap-1 mt-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}>
                    <AlertCircle className="w-3 h-3" />
                    {errors.vendor}
                  </div>
                )}
              </div>

              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Category
                </label>
                <Input
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="e.g., Payments, Analytics, Communications"
                  disabled={isLoading}
                  className={isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''}
                />
              </div>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Service URL
                </label>
                <Input
                  value={serviceUrl}
                  onChange={(e) => setServiceUrl(e.target.value)}
                  placeholder="https://dashboard.stripe.com"
                  disabled={isLoading}
                  className={`${isDarkMode ? 'bg-gray-700 border-gray-600 text-white' : ''} ${
                    errors.service_url ? 'border-red-500' : ''
                  }`}
                />
                {errors.service_url && (
                  <div className={`flex items-center gap-1 mt-1 text-xs ${isDarkMode ? 'text-red-400' : 'text-red-600'}`}>
                    <AlertCircle className="w-3 h-3" />
                    {errors.service_url}
                  </div>
                )}
              </div>

              <div>
                <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                  Status
                </label>
                <select
                  value={status}
                  onChange={(e) => setStatus(e.target.value)}
                  disabled={isLoading}
                  className={selectClass}
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of this service and how it is used"
                className={`w-full px-3 py-2 rounded-lg border resize-none ${
                  isDarkMode
                    ? 'bg-gray-700 border-gray-600 text-white placeholder:text-gray-400'
                    : 'bg-white border-gray-300 text-gray-900 placeholder:text-gray-500'
                }`}
              />
            </div>

            <div>
              <label className={`block text-sm mb-1.5 ${isDarkMode ? 'text-gray-300' : 'text-gray-700'}`}>
                Icon
              </label>
              <IconUpload value={icon} onChange={setIcon} isDarkMode={isDarkMode} />
            </div>
          </div>
        </div>

        {/* Links */}
        <div className={`p-6 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Links
          </h3>
          <p className={`mb-4 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            Named links to documentation, API references, status pages, etc.
          </p>
          <KeyValueEditor
            value={links}
            onChange={setLinks}
            isDarkMode={isDarkMode}
            keyPlaceholder="Label (e.g., docs)"
            valuePlaceholder="URL (e.g., https://docs.stripe.com)"
            disabled={isLoading}
          />
        </div>

        {/* Identifiers */}
        <div className={`p-6 rounded-lg border ${
          isDarkMode ? 'bg-gray-800 border-gray-700' : 'bg-white border-gray-200'
        }`}>
          <h3 className={`mb-4 font-semibold ${isDarkMode ? 'text-white' : 'text-gray-900'}`}>
            Identifiers
          </h3>
          <p className={`mb-4 text-sm ${isDarkMode ? 'text-gray-400' : 'text-gray-600'}`}>
            External IDs such as account ID, org ID, or API key names.
          </p>
          <KeyValueEditor
            value={identifiers}
            onChange={setIdentifiers}
            isDarkMode={isDarkMode}
            keyPlaceholder="Label (e.g., account_id)"
            valuePlaceholder="Value (e.g., acct_123)"
            disabled={isLoading}
          />
        </div>
      </form>
    </div>
  )
}
