import { useState } from 'react'

import { AlertCircle, Save, X } from 'lucide-react'

import type { Organization, OrganizationCreate } from '@/types'

import { Button } from '../../ui/button'
import { Card, CardContent } from '../../ui/card'
import { IconUpload } from '../../ui/icon-upload'
import { Input } from '../../ui/input'

interface OrganizationFormProps {
  error?: null | { message?: string; response?: { data?: { detail?: string } } }
  isLoading?: boolean
  onCancel: () => void
  onSave: (org: OrganizationCreate) => void
  organization: null | Organization
}

export function OrganizationForm({
  error,
  isLoading = false,
  onCancel,
  onSave,
  organization,
}: OrganizationFormProps) {
  const isEditing = !!organization

  const [name, setName] = useState(organization?.name || '')
  const [slug, setSlug] = useState(organization?.slug || '')
  const [description, setDescription] = useState(
    organization?.description || '',
  )
  const [icon, setIcon] = useState(organization?.icon || '')
  const [errors, setErrors] = useState<Record<string, string>>({})

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Organization name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9-_]+$/.test(slug)) {
      newErrors.slug =
        'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!validate()) return

    onSave({
      description: description.trim() || null,
      icon: icon.trim() || null,
      name: name.trim(),
      slug: slug.trim(),
    })
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(
        value
          .toLowerCase()
          .replace(/[^a-z0-9\s-_]/g, '')
          .replace(/\s+/g, '-')
          .replace(/-+/g, '-')
          .trim(),
      )
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-primary text-base font-medium">
            {isEditing ? 'Edit Organization' : 'Create New Organization'}
          </h2>
          <p className="text-secondary mt-1 text-sm">
            {isEditing
              ? 'Update organization information and settings'
              : 'Create a new organization to group projects and control access'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button disabled={isLoading} onClick={onCancel} variant="outline">
            <X className="mr-2 size-4" />
            Cancel
          </Button>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={isLoading}
            onClick={handleSubmit}
          >
            <Save className="mr-2 size-4" />
            {isLoading
              ? 'Saving...'
              : isEditing
                ? 'Save Changes'
                : 'Create Organization'}
          </Button>
        </div>
      </div>

      {/* API Error */}
      {error && (
        <div className="border-danger bg-danger rounded-lg border p-4">
          <div className="flex items-start gap-3">
            <AlertCircle className="text-danger size-5 shrink-0" />
            <div>
              <div className="text-danger font-medium">
                Failed to save organization
              </div>
              <div className="text-danger mt-1 text-sm">
                {error?.response?.data?.detail ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Form */}
      <form className="space-y-6" onSubmit={handleSubmit}>
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label className="text-secondary mb-1.5 block text-sm">
                  Organization Name <span className="text-red-500">*</span>
                </label>
                <Input
                  className={` ${errors.name ? 'border-red-500' : ''}`}
                  disabled={isLoading}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Engineering"
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
                  <label className="text-secondary mb-1.5 block text-sm">
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
                    disabled={isLoading}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., engineering"
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
              <label className="text-secondary mb-1.5 block text-sm">
                Description
              </label>
              <textarea
                className="border-input bg-background text-foreground placeholder:text-muted-foreground w-full resize-none rounded-lg border px-3 py-2"
                disabled={isLoading}
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description of the organization's purpose"
                rows={3}
                value={description}
              />
            </div>

            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Icon
              </label>
              <IconUpload onChange={setIcon} value={icon} />
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
