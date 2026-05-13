import { useState } from 'react'

import { AlertCircle, Save, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { slugify } from '@/lib/utils'
import type { LinkDefinition, LinkDefinitionCreate } from '@/types'

interface LinkDefinitionFormProps {
  error?: unknown
  isLoading?: boolean
  linkDefinition: LinkDefinition | null
  onCancel: () => void
  onSave: (orgSlug: string, data: LinkDefinitionCreate) => void
}

export function LinkDefinitionForm({
  error,
  isLoading = false,
  linkDefinition,
  onCancel,
  onSave,
}: LinkDefinitionFormProps) {
  const isEditing = !!linkDefinition
  const { organizations, selectedOrganization } = useOrganization()

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
      description: description.trim() || null,
      icon: icon.trim() || null,
      name: name.trim(),
      slug: slug.trim(),
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
          <h2 className="text-primary text-base font-medium">
            {isEditing ? 'Edit Link Definition' : 'Create Link Definition'}
          </h2>
          <p className="text-secondary mt-1">
            Defines a type of project link displayed on the project details
            page.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            disabled={isLoading}
            onClick={onCancel}
            type="button"
            variant="outline"
          >
            <X className="mr-2 size-4" />
            Cancel
          </Button>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={isLoading}
            onClick={handleSubmit}
            type="button"
          >
            <Save className="mr-2 size-4" />
            {isLoading ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {!!error && (
        <ErrorBanner error={error} title="Failed to save link definition" />
      )}

      {/* Form */}
      <form className="space-y-6" onSubmit={handleSubmit}>
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="link-def-org"
              >
                Organization <span className="text-red-500">*</span>
              </label>
              <select
                className={`border-input bg-background text-foreground w-full rounded-lg border px-3 py-2 text-sm ${isEditing || isLoading || organizations.length <= 1 ? 'cursor-not-allowed opacity-60' : ''} ${
                  errors.organization ? 'border-red-500' : ''
                }`}
                disabled={isEditing || isLoading || organizations.length <= 1}
                id="link-def-org"
                onChange={(e) => setOrgSlug(e.target.value)}
                value={orgSlug}
              >
                <option value="">Select organization...</option>
                {organizations.map((org) => (
                  <option key={org.slug} value={org.slug}>
                    {org.name}
                  </option>
                ))}
              </select>
              {errors.organization && (
                <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                  <AlertCircle className="size-3" />
                  {errors.organization}
                </div>
              )}
            </div>

            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="link-def-name"
                >
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  className={` ${errors.name ? 'border-red-500' : ''}`}
                  disabled={isLoading}
                  id="link-def-name"
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., GitHub Repository"
                  value={name}
                />
                {errors.name && (
                  <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                    <AlertCircle className="size-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div>
                  <label
                    className="text-secondary mb-1.5 block text-sm"
                    htmlFor="link-def-slug"
                  >
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
                    disabled={isLoading}
                    id="link-def-slug"
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., github-repository"
                    value={slug}
                  />
                  {errors.slug && (
                    <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                      <AlertCircle className="size-3" />
                      {errors.slug}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="link-def-description"
              >
                Description
              </label>
              <textarea
                className="border-input bg-background text-foreground placeholder:text-muted-foreground w-full resize-none rounded-lg border px-3 py-2"
                disabled={isLoading}
                id="link-def-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of this link definition"
                rows={3}
                value={description}
              />
            </div>

            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Icon
              </label>
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
                <div>
                  <p className="text-tertiary mb-1.5 text-xs">Pick an icon</p>
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
                  <p className="text-tertiary mb-1.5 text-xs">
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

            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="link-def-url-template"
              >
                URL Template
              </label>
              <Input
                className=""
                disabled={isLoading}
                id="link-def-url-template"
                onChange={(e) => setUrlTemplate(e.target.value)}
                placeholder="e.g., https://github.com/{organization}/{project}"
                value={urlTemplate}
              />
              <p className="text-tertiary mt-1 text-xs">
                URL template with placeholders in curly braces
              </p>
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
