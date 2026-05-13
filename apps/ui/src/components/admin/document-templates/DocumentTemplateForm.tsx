import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { AlertCircle, Save, X } from 'lucide-react'

import { listProjectTypes } from '@/api/endpoints'
import { TagCombobox } from '@/components/documents/TagCombobox'
import { Button } from '@/components/ui/button'
import { Card, CardContent } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { slugify } from '@/lib/utils'
import type {
  DocumentTemplate,
  DocumentTemplateCreate,
  ProjectType,
  TagRef,
} from '@/types'

interface DocumentTemplateFormProps {
  documentTemplate: DocumentTemplate | null
  error?: unknown
  isLoading?: boolean
  onCancel: () => void
  onSave: (orgSlug: string, data: DocumentTemplateCreate) => void
}

export function DocumentTemplateForm({
  documentTemplate,
  error,
  isLoading = false,
  onCancel,
  onSave,
}: DocumentTemplateFormProps) {
  const isEditing = !!documentTemplate
  const { selectedOrganization } = useOrganization()
  const orgSlug =
    documentTemplate?.organization?.slug || selectedOrganization?.slug || ''

  const [name, setName] = useState(documentTemplate?.name || '')
  const [slug, setSlug] = useState(documentTemplate?.slug || '')
  const [description, setDescription] = useState(
    documentTemplate?.description || '',
  )
  const [icon, setIcon] = useState(documentTemplate?.icon || '')
  const handleIconChange = useIconWithCleanup(icon, setIcon)
  const [title, setTitle] = useState(documentTemplate?.title || '')
  const [content, setContent] = useState(documentTemplate?.content || '')
  const [tags, setTags] = useState<TagRef[]>(documentTemplate?.tags || [])
  const [projectTypeSlugs, setProjectTypeSlugs] = useState<string[]>(
    documentTemplate?.project_type_slugs || [],
  )
  const [sortOrder, setSortOrder] = useState<string>(
    String(documentTemplate?.sort_order ?? 0),
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: projectTypes = [] } = useQuery<ProjectType[]>({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listProjectTypes(orgSlug, signal),
    queryKey: ['projectTypes', orgSlug],
  })

  const validate = () => {
    const newErrors: Record<string, string> = {}
    if (!name.trim()) newErrors.name = 'Name is required'
    if (!slug.trim()) newErrors.slug = 'Slug is required'
    if (slug && !/^[a-z0-9_-]+$/.test(slug)) {
      newErrors.slug =
        'Slug must be lowercase and can only contain letters, numbers, hyphens, and underscores'
    }
    if (sortOrder.trim() && Number.isNaN(Number(sortOrder))) {
      newErrors.sort_order = 'Sort order must be a number'
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (isLoading || !validate() || !orgSlug) return

    onSave(orgSlug, {
      content,
      description: description.trim() || null,
      icon: icon.trim() || null,
      name: name.trim(),
      project_type_slugs: projectTypeSlugs,
      slug: slug.trim(),
      sort_order: sortOrder.trim() ? Number(sortOrder) : 0,
      tags: tags.map((t) => t.slug),
      title: title.trim() || null,
    })
  }

  const handleNameChange = (value: string) => {
    setName(value)
    if (!isEditing) {
      setSlug(slugify(value))
    }
  }

  const toggleProjectType = (ptSlug: string) => {
    setProjectTypeSlugs((prev) =>
      prev.includes(ptSlug)
        ? prev.filter((s) => s !== ptSlug)
        : [...prev, ptSlug],
    )
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-primary text-base font-medium">
            {isEditing ? 'Edit Document Template' : 'Create Document Template'}
          </h2>
          <p className="text-secondary mt-1">
            Reusable document skeleton offered when authoring project documents.
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
        <ErrorBanner error={error} title="Failed to save document template" />
      )}

      <form className="space-y-6" onSubmit={handleSubmit}>
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label
                  className="text-secondary mb-1.5 block text-sm"
                  htmlFor="document-tpl-name"
                >
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  className={errors.name ? 'border-red-500' : ''}
                  disabled={isLoading}
                  id="document-tpl-name"
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Architecture Decision Record"
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
                    htmlFor="document-tpl-slug"
                  >
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    className={errors.slug ? 'border-red-500' : ''}
                    disabled={isLoading}
                    id="document-tpl-slug"
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., adr"
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
                htmlFor="document-tpl-description"
              >
                Description
              </label>
              <textarea
                className="border-input bg-background text-foreground placeholder:text-muted-foreground w-full resize-none rounded-lg border px-3 py-2"
                disabled={isLoading}
                id="document-tpl-description"
                onChange={(e) => setDescription(e.target.value)}
                placeholder="Brief description shown when picking a template"
                rows={2}
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
                htmlFor="document-tpl-title"
              >
                Default Document Title
              </label>
              <Input
                disabled={isLoading}
                id="document-tpl-title"
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Pre-fills the title field of new documents"
                value={title}
              />
            </div>

            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="document-tpl-content"
              >
                Content
              </label>
              <textarea
                className="border-input bg-background text-foreground placeholder:text-muted-foreground w-full resize-y rounded-lg border px-3 py-2 font-mono text-sm"
                disabled={isLoading}
                id="document-tpl-content"
                onChange={(e) => setContent(e.target.value)}
                placeholder="Markdown body that pre-fills new documents"
                rows={10}
                value={content}
              />
            </div>

            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Default Tags
              </label>
              <p className="text-tertiary mb-2 text-xs">
                Tags applied to documents created from this template.
              </p>
              {orgSlug && (
                <TagCombobox
                  onChange={setTags}
                  orgSlug={orgSlug}
                  selected={tags}
                  variant="full"
                />
              )}
            </div>

            <div>
              <label className="text-secondary mb-1.5 block text-sm">
                Project Types
              </label>
              <p className="text-tertiary mb-2 text-xs">
                Limit this template to specific project types. Leave empty to
                offer it for every project type.
              </p>
              {projectTypeSlugs.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {projectTypeSlugs.map((ptSlug) => {
                    const pt = projectTypes.find((p) => p.slug === ptSlug)
                    return (
                      <span
                        className="bg-secondary text-primary inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs"
                        key={ptSlug}
                      >
                        {pt?.name ?? ptSlug}
                        <button
                          aria-label={`Remove ${pt?.name ?? ptSlug}`}
                          className="text-tertiary hover:text-primary border-0 bg-transparent p-0"
                          onClick={() => toggleProjectType(ptSlug)}
                          type="button"
                        >
                          <X className="size-3" />
                        </button>
                      </span>
                    )
                  })}
                </div>
              )}
              <select
                className="border-input bg-background text-foreground w-full rounded-lg border px-3 py-2 text-sm"
                disabled={isLoading || !orgSlug}
                onChange={(e) => {
                  if (e.target.value) toggleProjectType(e.target.value)
                }}
                value=""
              >
                <option value="">Add project type...</option>
                {projectTypes
                  .filter((pt) => !projectTypeSlugs.includes(pt.slug))
                  .map((pt) => (
                    <option key={pt.slug} value={pt.slug}>
                      {pt.name}
                    </option>
                  ))}
              </select>
            </div>

            <div>
              <label
                className="text-secondary mb-1.5 block text-sm"
                htmlFor="document-tpl-sort-order"
              >
                Sort Order
              </label>
              <Input
                className={errors.sort_order ? 'border-red-500' : ''}
                disabled={isLoading}
                id="document-tpl-sort-order"
                onChange={(e) => setSortOrder(e.target.value)}
                placeholder="0"
                type="number"
                value={sortOrder}
              />
              <p className="text-tertiary mt-1 text-xs">
                Lower values appear first in the template picker.
              </p>
              {errors.sort_order && (
                <div className="text-danger mt-1 flex items-center gap-1 text-xs">
                  <AlertCircle className="size-3" />
                  {errors.sort_order}
                </div>
              )}
            </div>
          </CardContent>
        </Card>
      </form>
    </div>
  )
}
