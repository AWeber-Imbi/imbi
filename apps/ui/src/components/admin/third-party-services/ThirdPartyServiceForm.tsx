import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { IconUpload } from '@/components/ui/icon-upload'
import { IconPicker } from '@/components/ui/icon-picker'
import { KeyValueEditor } from '@/components/ui/key-value-editor'
import { FormHeader } from '@/components/admin/form-header'
import { useOrganization } from '@/contexts/OrganizationContext'
import { listTeams } from '@/api/endpoints'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { slugify } from '@/lib/utils'
import type { Team, ThirdPartyService, ThirdPartyServiceCreate } from '@/types'

interface ThirdPartyServiceFormProps {
  service: ThirdPartyService | null
  onSave: (svc: ThirdPartyServiceCreate) => void
  onCancel: () => void
  isLoading?: boolean
  error?: { response?: { data?: { detail?: string } }; message?: string } | null
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
  isLoading = false,
  error,
}: ThirdPartyServiceFormProps) {
  const isEditing = !!service
  const { selectedOrganization } = useOrganization()

  const [name, setName] = useState(service?.name || '')
  const [slug, setSlug] = useState(service?.slug || '')
  const [description, setDescription] = useState(service?.description || '')
  const [icon, setIcon] = useState(service?.icon || '')
  const handleIconChange = useIconWithCleanup(icon, setIcon)
  const [vendor, setVendor] = useState(service?.vendor || '')
  const [serviceUrl, setServiceUrl] = useState(service?.service_url || '')
  const [category, setCategory] = useState(service?.category || '')
  const [status, setStatus] = useState<
    'active' | 'deprecated' | 'evaluating' | 'inactive'
  >(
    (service?.status as 'active' | 'deprecated' | 'evaluating' | 'inactive') ||
      'active',
  )
  const [links, setLinks] = useState<Record<string, string | number>>(
    (service?.links as Record<string, string | number> | undefined) || {},
  )
  const [identifiers, setIdentifiers] = useState<
    Record<string, string | number>
  >((service?.identifiers as Record<string, string | number> | undefined) || {})
  const orgSlug = selectedOrganization?.slug || ''
  const [teamSlug, setTeamSlug] = useState(
    (service?.team?.slug as string | undefined) || '',
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: teams = [] } = useQuery({
    queryKey: ['teams', orgSlug],
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    enabled: !!orgSlug,
  })

  const orgTeams = teams.filter((t: Team) => t.organization.slug === orgSlug)

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Service name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9_-]+$/.test(slug)) {
      newErrors.slug =
        'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (!vendor.trim()) newErrors.vendor = 'Vendor is required'
    if (serviceUrl && !/^https?:\/\/.+/.test(serviceUrl)) {
      newErrors.service_url =
        'Must be a valid URL starting with http:// or https://'
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSave = () => {
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
      team_slug: teamSlug || null,
    })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    handleSave()
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(slugify(value))
    }
  }

  const selectClass = `w-full px-3 py-2 rounded-lg border text-sm border-input bg-background text-foreground`

  return (
    <div className="space-y-6">
      {/* Header */}
      <FormHeader
        title={
          isEditing ? 'Edit Third-Party Service' : 'Add Third-Party Service'
        }
        subtitle={
          isEditing
            ? 'Update service information'
            : 'Register a new external SaaS or managed service'
        }
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        createLabel="Create Service"
      />

      {/* API Error */}
      {error && (
        <div className="rounded-lg border border-danger bg-danger p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="h-5 w-5 flex-shrink-0 text-danger" />
            <div>
              <div className="font-medium text-danger">
                Failed to save service
              </div>
              <div className="mt-1 text-sm text-danger">
                {error?.response?.data?.detail ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Form */}
      <form
        id="third-party-service-form"
        onSubmit={handleSubmit}
        className="space-y-6"
      >
        {/* Basic Information */}
        <div className="rounded-lg border border-border bg-card p-6">
          <h3 className="mb-4 text-sm font-medium text-primary">
            Service Information
          </h3>

          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm text-secondary">
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
                  <option key={team.slug} value={team.slug}>
                    {team.name}
                  </option>
                ))}
              </select>
            </div>

            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Service Name <span className="text-danger">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Stripe"
                  disabled={isLoading}
                  className={` ${errors.name ? 'border-danger' : ''}`}
                />
                {errors.name && (
                  <div
                    className={
                      'mt-1 flex items-center gap-1 text-xs text-danger'
                    }
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div>
                  <label className="mb-1.5 block text-sm text-secondary">
                    Slug <span className="text-danger">*</span>
                  </label>
                  <Input
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., stripe"
                    disabled={isLoading}
                    className={` ${errors.slug ? 'border-danger' : ''}`}
                  />
                  {errors.slug && (
                    <div
                      className={
                        'mt-1 flex items-center gap-1 text-xs text-danger'
                      }
                    >
                      <AlertCircle className="h-3 w-3" />
                      {errors.slug}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Vendor <span className="text-danger">*</span>
                </label>
                <Input
                  value={vendor}
                  onChange={(e) => setVendor(e.target.value)}
                  placeholder="e.g., Stripe, Inc."
                  disabled={isLoading}
                  className={` ${errors.vendor ? 'border-danger' : ''}`}
                />
                {errors.vendor && (
                  <div
                    className={
                      'mt-1 flex items-center gap-1 text-xs text-danger'
                    }
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.vendor}
                  </div>
                )}
              </div>

              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Category
                </label>
                <Input
                  value={category}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="e.g., Payments, Analytics, Communications"
                  disabled={isLoading}
                  className=""
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Service URL
                </label>
                <Input
                  value={serviceUrl}
                  onChange={(e) => setServiceUrl(e.target.value)}
                  placeholder="https://dashboard.stripe.com"
                  disabled={isLoading}
                  className={` ${errors.service_url ? 'border-danger' : ''}`}
                />
                {errors.service_url && (
                  <div
                    className={
                      'mt-1 flex items-center gap-1 text-xs text-danger'
                    }
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.service_url}
                  </div>
                )}
              </div>

              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Status
                </label>
                <select
                  value={status}
                  onChange={(e) =>
                    setStatus(
                      e.target.value as
                        | 'active'
                        | 'deprecated'
                        | 'evaluating'
                        | 'inactive',
                    )
                  }
                  disabled={isLoading}
                  className={selectClass}
                >
                  {STATUS_OPTIONS.map((opt) => (
                    <option key={opt.value} value={opt.value}>
                      {opt.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of this service and how it is used"
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-foreground placeholder:text-muted-foreground"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Icon
              </label>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <p className="mb-1.5 text-xs text-tertiary">Pick an icon</p>
                  <IconPicker
                    value={
                      !icon.startsWith('/') && !icon.startsWith('http')
                        ? icon
                        : ''
                    }
                    onChange={handleIconChange}
                  />
                </div>
                <div>
                  <p className="mb-1.5 text-xs text-tertiary">
                    Or upload a custom image
                  </p>
                  <IconUpload
                    value={
                      icon.startsWith('/') || icon.startsWith('http')
                        ? icon
                        : ''
                    }
                    onChange={handleIconChange}
                  />
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Links */}
        <div className="rounded-lg border border-border bg-card p-6">
          <h3 className="mb-4 text-sm font-medium text-primary">Links</h3>
          <p className="mb-4 text-sm text-secondary">
            Named links to documentation, API references, status pages, etc.
          </p>
          <KeyValueEditor
            value={links}
            onChange={setLinks}
            keyPlaceholder="Label (e.g., docs)"
            valuePlaceholder="URL (e.g., https://docs.stripe.com)"
            disabled={isLoading}
          />
        </div>

        {/* Identifiers */}
        <div className="rounded-lg border border-border bg-card p-6">
          <h3 className="mb-4 text-sm font-medium text-primary">Identifiers</h3>
          <p className="mb-4 text-sm text-secondary">
            External IDs such as account ID, org ID, or API key names.
          </p>
          <KeyValueEditor
            value={identifiers}
            onChange={setIdentifiers}
            keyPlaceholder="Label (e.g., account_id)"
            valuePlaceholder="Value (e.g., acct_123)"
            disabled={isLoading}
          />
        </div>
      </form>
    </div>
  )
}
