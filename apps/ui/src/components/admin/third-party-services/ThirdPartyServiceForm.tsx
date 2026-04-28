import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle } from 'lucide-react'

import { listTeams } from '@/api/endpoints'
import { FormHeader } from '@/components/admin/form-header'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { Input } from '@/components/ui/input'
import { KeyValueEditor } from '@/components/ui/key-value-editor'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { slugify } from '@/lib/utils'
import type { Team, ThirdPartyService, ThirdPartyServiceCreate } from '@/types'

interface ThirdPartyServiceFormProps {
  error?: null | { message?: string; response?: { data?: { detail?: string } } }
  isLoading?: boolean
  onCancel: () => void
  onSave: (svc: ThirdPartyServiceCreate) => void
  service: null | ThirdPartyService
}

const STATUS_OPTIONS = [
  { label: 'Active', value: 'active' },
  { label: 'Evaluating', value: 'evaluating' },
  { label: 'Deprecated', value: 'deprecated' },
  { label: 'Inactive', value: 'inactive' },
]

export function ThirdPartyServiceForm({
  error,
  isLoading = false,
  onCancel,
  onSave,
  service,
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
  const [links, setLinks] = useState<Record<string, number | string>>(
    (service?.links as Record<string, number | string> | undefined) || {},
  )
  const [identifiers, setIdentifiers] = useState<
    Record<string, number | string>
  >((service?.identifiers as Record<string, number | string> | undefined) || {})
  const orgSlug = selectedOrganization?.slug || ''
  const [teamSlug, setTeamSlug] = useState(
    (service?.team?.slug as string | undefined) || '',
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: teams = [] } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: ['teams', orgSlug],
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
      category: category.trim() || null,
      description: description.trim() || null,
      icon: icon.trim() || null,
      identifiers,
      links: links as Record<string, string>,
      name: name.trim(),
      service_url: serviceUrl.trim() || null,
      slug: slug.trim(),
      status,
      team_slug: teamSlug || null,
      vendor: vendor.trim(),
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
        createLabel="Create Service"
        isEditing={isEditing}
        isLoading={isLoading}
        onCancel={onCancel}
        onSave={handleSave}
        subtitle={
          isEditing
            ? 'Update service information'
            : 'Register a new external SaaS or managed service'
        }
        title={
          isEditing ? 'Edit Third-Party Service' : 'Add Third-Party Service'
        }
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
        className="space-y-6"
        id="third-party-service-form"
        onSubmit={handleSubmit}
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
                className={selectClass}
                disabled={isLoading || !orgSlug}
                onChange={(e) => setTeamSlug(e.target.value)}
                value={teamSlug}
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
                  className={` ${errors.name ? 'border-danger' : ''}`}
                  disabled={isLoading}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Stripe"
                  value={name}
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
                    className={` ${errors.slug ? 'border-danger' : ''}`}
                    disabled={isLoading}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., stripe"
                    value={slug}
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
                  className={` ${errors.vendor ? 'border-danger' : ''}`}
                  disabled={isLoading}
                  onChange={(e) => setVendor(e.target.value)}
                  placeholder="e.g., Stripe, Inc."
                  value={vendor}
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
                  className=""
                  disabled={isLoading}
                  onChange={(e) => setCategory(e.target.value)}
                  placeholder="e.g., Payments, Analytics, Communications"
                  value={category}
                />
              </div>
            </div>

            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              <div>
                <label className="mb-1.5 block text-sm text-secondary">
                  Service URL
                </label>
                <Input
                  className={` ${errors.service_url ? 'border-danger' : ''}`}
                  disabled={isLoading}
                  onChange={(e) => setServiceUrl(e.target.value)}
                  placeholder="https://dashboard.stripe.com"
                  value={serviceUrl}
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
                  className={selectClass}
                  disabled={isLoading}
                  onChange={(e) =>
                    setStatus(
                      e.target.value as
                        | 'active'
                        | 'deprecated'
                        | 'evaluating'
                        | 'inactive',
                    )
                  }
                  value={status}
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
                className="w-full resize-none rounded-lg border border-input bg-background px-3 py-2 text-foreground placeholder:text-muted-foreground"
                disabled={isLoading}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of this service and how it is used"
                rows={3}
                value={description}
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
                    onChange={handleIconChange}
                    value={
                      !icon.startsWith('/') && !icon.startsWith('http')
                        ? icon
                        : ''
                    }
                  />
                </div>
                <div>
                  <p className="mb-1.5 text-xs text-tertiary">
                    Or upload a custom image
                  </p>
                  <IconUpload
                    onChange={handleIconChange}
                    value={
                      icon.startsWith('/') || icon.startsWith('http')
                        ? icon
                        : ''
                    }
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
            disabled={isLoading}
            keyPlaceholder="Label (e.g., docs)"
            onChange={setLinks}
            value={links}
            valuePlaceholder="URL (e.g., https://docs.stripe.com)"
          />
        </div>

        {/* Identifiers */}
        <div className="rounded-lg border border-border bg-card p-6">
          <h3 className="mb-4 text-sm font-medium text-primary">Identifiers</h3>
          <p className="mb-4 text-sm text-secondary">
            External IDs such as account ID, org ID, or API key names.
          </p>
          <KeyValueEditor
            disabled={isLoading}
            keyPlaceholder="Label (e.g., account_id)"
            onChange={setIdentifiers}
            value={identifiers}
            valuePlaceholder="Value (e.g., acct_123)"
          />
        </div>
      </form>
    </div>
  )
}
