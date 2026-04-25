import { useState } from 'react'
import { Save, AlertCircle, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { slugify } from '@/lib/utils'
import type { LinkDefinition, LinkDefinitionCreate } from '@/types'

interface LinkDefinitionFormProps {
  linkDefinition: LinkDefinition | null
  onSave: (orgSlug: string, data: LinkDefinitionCreate) => void
  onCancel: () => void
  isLoading?: boolean
  error?: unknown
}

export function LinkDefinitionForm({
  linkDefinition,
  onSave,
  onCancel,
  isLoading = false,
  error,
}: LinkDefinitionFormProps) {
  const isEditing = !!linkDefinition
  const { selectedOrganization, organizations } = useOrganization()

  const [name, setName] = useState(linkDefinition?.name || '')
  const [slug, setSlug] = useState(linkDefinition?.slug || '')
  const [description, setDescription] = useState(
    linkDefinition?.description || '',
  )
  const [icon, setIcon] = useState(linkDefinition?.icon || '')
  const handleIconChange = useIconWithCleanup(icon, setIcon)
  const [urlTemplate, setUrlTemplate] = useState(
    linkDefinition?.url_template || '',
  )
  const [orgSlug, setOrgSlug] = useState(
    linkDefinition?.organization?.slug || selectedOrganization?.slug || '',
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9_-]+$/.test(slug)) {
      newErrors.slug =
        'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (!orgSlug) newErrors.organization = 'Organization is required'
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (isLoading || !validate()) return

    onSave(orgSlug, {
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || null,
      icon: icon.trim() || null,
      url_template: urlTemplate.trim() || null,
    })
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(slugify(value))
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-medium text-primary">
            {isEditing ? 'Edit Link Definition' : 'Create Link Definition'}
          </h2>
          <p className="mt-1 text-secondary">
            Defines a type of project link displayed on the project details
            page.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="outline"
            onClick={onCancel}
            disabled={isLoading}
          >
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            type="button"
            onClick={handleSubmit}
            disabled={isLoading}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Save className="mr-2 h-4 w-4" />
            {isLoading ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {!!error && (
        <ErrorBanner title="Failed to save link definition" error={error} />
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div>
              <label
                htmlFor="link-def-org"
                className="mb-1.5 block text-sm text-secondary"
              >
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                id="link-def-org"
                value={orgSlug}
                onChange={(e) => setOrgSlug(e.target.value)}
                disabled={isEditing || isLoading || organizations.length <= 1}
                className={`w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground ${isEditing || isLoading || organizations.length <= 1 ? 'cursor-not-allowed opacity-60' : ''} ${
                  errors.organization ? 'border-red-500' : ''
                }`}
              >
                <option value="">Select organization...</option>
                {organizations.map((org) => (
                  <option key={org.slug} value={org.slug}>
                    {org.name}
                  </option>
                ))}
              </select>
              {errors.organization && (
                <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                  <AlertCircle className="h-3 w-3" />
                  {errors.organization}
                </div>
              )}
            </div>

            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label
                  htmlFor="link-def-name"
                  className="mb-1.5 block text-sm text-secondary"
                >
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  id="link-def-name"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., GitHub Repository"
                  disabled={isLoading}
                  className={` ${errors.name ? 'border-red-500' : ''}`}
                />
                {errors.name && (
                  <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                    <AlertCircle className="h-3 w-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div>
                  <label
                    htmlFor="link-def-slug"
                    className="mb-1.5 block text-sm text-secondary"
                  >
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    id="link-def-slug"
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., github-repository"
                    disabled={isLoading}
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
                  />
                  {errors.slug && (
                    <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                      <AlertCircle className="h-3 w-3" />
                      {errors.slug}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div>
              <label
                htmlFor="link-def-description"
                className="mb-1.5 block text-sm text-secondary"
              >
                Description
              </label>
              <textarea
                id="link-def-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of this link definition"
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

            <div>
              <label
                htmlFor="link-def-url-template"
                className="mb-1.5 block text-sm text-secondary"
              >
                URL Template
              </label>
              <Input
                id="link-def-url-template"
                value={urlTemplate}
                onChange={(e) => setUrlTemplate(e.target.value)}
                placeholder="e.g., https://github.com/{organization}/{project}"
                disabled={isLoading}
                className=""
              />
              <p className="mt-1 text-xs text-tertiary">
                URL template with placeholders in curly braces
              </p>
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
