import { useState } from 'react'
import { Save, X, AlertCircle } from 'lucide-react'
import { Button } from '../../ui/button'
import { Input } from '../../ui/input'
import { IconUpload } from '../../ui/icon-upload'
import { Card, CardContent } from '../../ui/card'
import type { Organization, OrganizationCreate } from '@/types'

interface OrganizationFormProps {
  organization: Organization | null
  onSave: (org: OrganizationCreate) => void
  onCancel: () => void
  isLoading?: boolean
  error?: { response?: { data?: { detail?: string } }; message?: string } | null
}

export function OrganizationForm({
  organization,
  onSave,
  onCancel,
  isLoading = false,
  error,
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
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || null,
      icon: icon.trim() || null,
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
          <h2 className={'text-base font-medium text-primary'}>
            {isEditing ? 'Edit Organization' : 'Create New Organization'}
          </h2>
          <p className={'mt-1 text-sm text-secondary'}>
            {isEditing
              ? 'Update organization information and settings'
              : 'Create a new organization to group projects and control access'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={onCancel} disabled={isLoading}>
            <X className="mr-2 h-4 w-4" />
            Cancel
          </Button>
          <Button
            onClick={handleSubmit}
            disabled={isLoading}
            className="bg-action text-action-foreground hover:bg-action-hover"
          >
            <Save className="mr-2 h-4 w-4" />
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
        <div className={`rounded-lg border p-4 ${'border-danger bg-danger'}`}>
          <div className="flex items-start gap-3">
            <AlertCircle className={'h-5 w-5 flex-shrink-0 text-danger'} />
            <div>
              <div className={'font-medium text-danger'}>
                Failed to save organization
              </div>
              <div className={'mt-1 text-sm text-danger'}>
                {error?.response?.data?.detail ||
                  error?.message ||
                  'An error occurred'}
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Form */}
      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label className={'mb-1.5 block text-sm text-secondary'}>
                  Organization Name <span className="text-red-500">*</span>
                </label>
                <Input
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Engineering"
                  disabled={isLoading}
                  className={` ${errors.name ? 'border-red-500' : ''}`}
                />
                {errors.name && (
                  <div
                    className={`mt-1 flex items-center gap-1 text-xs ${'text-danger'}`}
                  >
                    <AlertCircle className="h-3 w-3" />
                    {errors.name}
                  </div>
                )}
              </div>

              {!isEditing && (
                <div>
                  <label className={'mb-1.5 block text-sm text-secondary'}>
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., engineering"
                    disabled={isLoading}
                    className={` ${errors.slug ? 'border-red-500' : ''}`}
                  />
                  {errors.slug && (
                    <div
                      className={`mt-1 flex items-center gap-1 text-xs ${'text-danger'}`}
                    >
                      <AlertCircle className="h-3 w-3" />
                      {errors.slug}
                    </div>
                  )}
                </div>
              )}
            </div>

            <div>
              <label className={'mb-1.5 block text-sm text-secondary'}>
                Description
              </label>
              <textarea
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={3}
                disabled={isLoading}
                placeholder="Brief description of the organization's purpose"
                className={`w-full resize-none rounded-lg border px-3 py-2 ${'border-input bg-background text-foreground placeholder:text-muted-foreground'}`}
              />
            </div>

            <div>
              <label className={'mb-1.5 block text-sm text-secondary'}>
                Icon
              </label>
              <IconUpload value={icon} onChange={setIcon} />
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
