import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Save, AlertCircle, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card, CardContent } from '@/components/ui/card'
import { ErrorBanner } from '@/components/ui/error-banner'
import { IconPicker } from '@/components/ui/icon-picker'
import { IconUpload } from '@/components/ui/icon-upload'
import { TagCombobox } from '@/components/notes/TagCombobox'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useIconWithCleanup } from '@/hooks/useIconWithCleanup'
import { listProjectTypes } from '@/api/endpoints'
import { slugify } from '@/lib/utils'
import type {
  NoteTemplate,
  NoteTemplateCreate,
  ProjectType,
  TagRef,
} from '@/types'

interface NoteTemplateFormProps {
  noteTemplate: NoteTemplate | null
  onSave: (orgSlug: string, data: NoteTemplateCreate) => void
  onCancel: () => void
  isLoading?: boolean
  error?: unknown
}

export function NoteTemplateForm({
  noteTemplate,
  onSave,
  onCancel,
  isLoading = false,
  error,
}: NoteTemplateFormProps) {
  const isEditing = !!noteTemplate
  const { selectedOrganization } = useOrganization()
  const orgSlug =
    noteTemplate?.organization?.slug || selectedOrganization?.slug || ''

  const [name, setName] = useState(noteTemplate?.name || '')
  const [slug, setSlug] = useState(noteTemplate?.slug || '')
  const [description, setDescription] = useState(
    noteTemplate?.description || '',
  )
  const [icon, setIcon] = useState(noteTemplate?.icon || '')
  const handleIconChange = useIconWithCleanup(icon, setIcon)
  const [title, setTitle] = useState(noteTemplate?.title || '')
  const [content, setContent] = useState(noteTemplate?.content || '')
  const [tags, setTags] = useState<TagRef[]>(noteTemplate?.tags || [])
  const [projectTypeSlugs, setProjectTypeSlugs] = useState<string[]>(
    noteTemplate?.project_type_slugs || [],
  )
  const [sortOrder, setSortOrder] = useState<string>(
    String(noteTemplate?.sort_order ?? 0),
  )
  const [errors, setErrors] = useState<Record<string, string>>({})

  const { data: projectTypes = [] } = useQuery<ProjectType[]>({
    queryKey: ['projectTypes', orgSlug],
    queryFn: ({ signal }) => listProjectTypes(orgSlug, signal),
    enabled: !!orgSlug,
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
      name: name.trim(),
      slug: slug.trim(),
      description: description.trim() || null,
      icon: icon.trim() || null,
      title: title.trim() || null,
      content,
      tags: tags.map((t) => t.slug),
      project_type_slugs: projectTypeSlugs,
      sort_order: sortOrder.trim() ? Number(sortOrder) : 0,
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
          <h2 className="text-base font-medium text-primary">
            {isEditing ? 'Edit Note Template' : 'Create Note Template'}
          </h2>
          <p className="mt-1 text-secondary">
            Reusable note skeleton offered when authoring project notes.
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
        <ErrorBanner title="Failed to save note template" error={error} />
      )}

      <form onSubmit={handleSubmit} className="space-y-6">
        <Card>
          <CardContent className="space-y-4 pt-6">
            <div
              className={`grid grid-cols-1 gap-4 ${!isEditing ? 'md:grid-cols-2' : ''}`}
            >
              <div>
                <label
                  htmlFor="note-tpl-name"
                  className="mb-1.5 block text-sm text-secondary"
                >
                  Name <span className="text-red-500">*</span>
                </label>
                <Input
                  id="note-tpl-name"
                  value={name}
                  onChange={(e) => handleNameChange(e.target.value)}
                  placeholder="e.g., Architecture Decision Record"
                  disabled={isLoading}
                  className={errors.name ? 'border-red-500' : ''}
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
                    htmlFor="note-tpl-slug"
                    className="mb-1.5 block text-sm text-secondary"
                  >
                    Slug <span className="text-red-500">*</span>
                  </label>
                  <Input
                    id="note-tpl-slug"
                    value={slug}
                    onChange={(e) => setSlug(e.target.value)}
                    placeholder="e.g., adr"
                    disabled={isLoading}
                    className={errors.slug ? 'border-red-500' : ''}
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
                htmlFor="note-tpl-description"
                className="mb-1.5 block text-sm text-secondary"
              >
                Description
              </label>
              <textarea
                id="note-tpl-description"
                value={description}
                onChange={(e) => setDescription(e.target.value)}
                rows={2}
                disabled={isLoading}
                placeholder="Brief description shown when picking a template"
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
                htmlFor="note-tpl-title"
                className="mb-1.5 block text-sm text-secondary"
              >
                Default Note Title
              </label>
              <Input
                id="note-tpl-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Pre-fills the title field of new notes"
                disabled={isLoading}
              />
            </div>

            <div>
              <label
                htmlFor="note-tpl-content"
                className="mb-1.5 block text-sm text-secondary"
              >
                Content
              </label>
              <textarea
                id="note-tpl-content"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={10}
                disabled={isLoading}
                placeholder="Markdown body that pre-fills new notes"
                className="w-full resize-y rounded-lg border border-input bg-background px-3 py-2 font-mono text-sm text-foreground placeholder:text-muted-foreground"
              />
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Default Tags
              </label>
              <p className="mb-2 text-xs text-tertiary">
                Tags applied to notes created from this template.
              </p>
              {orgSlug && (
                <TagCombobox
                  orgSlug={orgSlug}
                  selected={tags}
                  onChange={setTags}
                  variant="full"
                />
              )}
            </div>

            <div>
              <label className="mb-1.5 block text-sm text-secondary">
                Project Types
              </label>
              <p className="mb-2 text-xs text-tertiary">
                Limit this template to specific project types. Leave empty to
                offer it for every project type.
              </p>
              {projectTypeSlugs.length > 0 && (
                <div className="mb-2 flex flex-wrap gap-1">
                  {projectTypeSlugs.map((ptSlug) => {
                    const pt = projectTypes.find((p) => p.slug === ptSlug)
                    return (
                      <span
                        key={ptSlug}
                        className="inline-flex items-center gap-1 rounded-md bg-secondary px-2 py-0.5 text-xs text-primary"
                      >
                        {pt?.name ?? ptSlug}
                        <button
                          type="button"
                          onClick={() => toggleProjectType(ptSlug)}
                          className="border-0 bg-transparent p-0 text-tertiary hover:text-primary"
                          aria-label={`Remove ${pt?.name ?? ptSlug}`}
                        >
                          <X className="h-3 w-3" />
                        </button>
                      </span>
                    )
                  })}
                </div>
              )}
              <select
                value=""
                onChange={(e) => {
                  if (e.target.value) toggleProjectType(e.target.value)
                }}
                disabled={isLoading || !orgSlug}
                className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm text-foreground"
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
                htmlFor="note-tpl-sort-order"
                className="mb-1.5 block text-sm text-secondary"
              >
                Sort Order
              </label>
              <Input
                id="note-tpl-sort-order"
                type="number"
                value={sortOrder}
                onChange={(e) => setSortOrder(e.target.value)}
                placeholder="0"
                disabled={isLoading}
                className={errors.sort_order ? 'border-red-500' : ''}
              />
              <p className="mt-1 text-xs text-tertiary">
                Lower values appear first in the template picker.
              </p>
              {errors.sort_order && (
                <div className="mt-1 flex items-center gap-1 text-xs text-danger">
                  <AlertCircle className="h-3 w-3" />
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
