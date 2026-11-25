import { useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { GitMerge, Pencil } from 'lucide-react'
import { toast } from 'sonner'

import { deleteTag, listTags, mergeTag, patchTag } from '@/api/endpoints'
import { AgentTagChip } from '@/components/agents/AgentTagChip'
import { AdminTable } from '@/components/ui/admin-table'
import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import { LabelSwatchPicker } from '@/components/ui/label-swatch-picker'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { useOrganization } from '@/contexts/OrganizationContext'
import { useHasPermission } from '@/hooks/useHasPermission'
import { extractApiErrorDetail } from '@/lib/apiError'
import { buildDiffPatch } from '@/lib/json-patch'
import { queryKeys } from '@/lib/queryKeys'
import type { PatchOperation, Tag } from '@/types'

import { AdminSection } from './AdminSection'

const documentCount = (t: Tag) => t.relationships?.documents?.count ?? 0
const agentCount = (t: Tag) => t.relationships?.agents?.count ?? 0

/**
 * The tags of the organization. Users create tags from the label and
 * tag pickers, so this page only edits, merges and deletes them.
 */
export function TagManagement() {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug ?? ''
  const canWrite = useHasPermission('tag:write', orgSlug)
  const canDelete = useHasPermission('tag:delete', orgSlug)
  const queryClient = useQueryClient()
  const [search, setSearch] = useState('')
  const [editing, setEditing] = useState<null | Tag>(null)
  const [merging, setMerging] = useState<null | Tag>(null)

  const tagsKey = queryKeys.tags(orgSlug)
  const {
    data: tags = [],
    error,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug,
    queryFn: ({ signal }) => listTags(orgSlug, signal),
    queryKey: tagsKey,
  })

  const onSuccess = () => {
    queryClient.invalidateQueries({ queryKey: tagsKey })
    // Cached agents and documents hold tag slugs and names. Reset them:
    // this removes the cached data, so that an editor cannot seed its
    // draft from a stale record before the refetch completes.
    for (const key of [
      queryKeys.agents(orgSlug),
      ['orgDocuments', orgSlug],
      ['projectDocuments', orgSlug],
      ['userDocuments', orgSlug],
    ]) {
      queryClient.resetQueries({ queryKey: key })
    }
    setEditing(null)
    setMerging(null)
  }
  const onError = (e: Error) => toast.error(extractApiErrorDetail(e))

  const update = useMutation({
    mutationFn: (args: { operations: PatchOperation[]; slug: string }) =>
      patchTag(orgSlug, args.slug, args.operations),
    onError,
    onSuccess,
  })
  const merge = useMutation({
    mutationFn: (args: { slug: string; target: string }) =>
      mergeTag(orgSlug, args.slug, args.target),
    onError,
    onSuccess,
  })
  const remove = useMutation({
    mutationFn: (slug: string) => deleteTag(orgSlug, slug),
    onError,
    onSuccess,
  })

  if (!orgSlug) {
    return (
      <div className="text-tertiary py-12 text-center">
        Select an organization to manage tags.
      </div>
    )
  }

  const q = search.toLowerCase()
  const rows = tags.filter(
    (t) => t.name.toLowerCase().includes(q) || t.slug.includes(q),
  )

  return (
    <AdminSection
      error={error}
      errorTitle="Failed to load tags"
      onSearchChange={setSearch}
      search={search}
      searchPlaceholder="Search tags..."
    >
      <AdminTable
        actions={(t) => (
          <>
            {canWrite && (
              <Button
                aria-label={`Edit ${t.name}`}
                onClick={() => setEditing(t)}
                size="sm"
                variant="ghost"
              >
                <Pencil className="size-4" />
              </Button>
            )}
            {canDelete && (
              <Button
                aria-label={`Merge ${t.name}`}
                onClick={() => setMerging(t)}
                size="sm"
                variant="ghost"
              >
                <GitMerge className="size-4" />
              </Button>
            )}
          </>
        )}
        columns={[
          {
            header: 'Tag',
            key: 'name',
            render: (t) => <AgentTagChip tag={t} />,
          },
          {
            header: 'Slug',
            key: 'slug',
            render: (t) => (
              <span className="text-tertiary font-mono text-xs">{t.slug}</span>
            ),
          },
          {
            cellAlign: 'right',
            header: 'Documents',
            headerAlign: 'right',
            key: 'documents',
            render: documentCount,
          },
          {
            cellAlign: 'right',
            header: 'Agents',
            headerAlign: 'right',
            key: 'agents',
            render: agentCount,
          },
        ]}
        emptyMessage={search ? 'No tags match.' : 'No tags yet.'}
        getDeleteDescription={(t) =>
          `Removes the tag from ${usage(t)}. This action cannot be undone.`
        }
        getDeleteLabel={(t) => t.name}
        getRowKey={(t) => t.slug}
        isDeleting={remove.isPending}
        loading={isLoading}
        onDelete={canDelete ? (t) => remove.mutate(t.slug) : undefined}
        rows={rows}
      />
      {editing && (
        <EditTagDialog
          isSaving={update.isPending}
          onClose={() => setEditing(null)}
          onSave={(operations) =>
            update.mutate({ operations, slug: editing.slug })
          }
          tag={editing}
        />
      )}
      {merging && (
        <MergeTagDialog
          isSaving={merge.isPending}
          onClose={() => setMerging(null)}
          onMerge={(target) => merge.mutate({ slug: merging.slug, target })}
          tag={merging}
          tags={tags}
        />
      )}
    </AdminSection>
  )
}

function EditTagDialog({
  isSaving,
  onClose,
  onSave,
  tag,
}: {
  isSaving: boolean
  onClose: () => void
  onSave: (operations: PatchOperation[]) => void
  tag: Tag
}) {
  const [name, setName] = useState(tag.name)
  const [description, setDescription] = useState(tag.description ?? '')
  const [color, setColor] = useState<null | string>(tag.color ?? null)

  const save = () => {
    // No value is ``undefined``, so every change is a ``replace``. The
    // API keeps the description when it gets ``null``, so a cleared
    // description is sent as ``''``.
    const operations = buildDiffPatch(
      {
        color: tag.color ?? null,
        description: tag.description ?? '',
        name: tag.name,
      },
      { color, description, name: name.trim() },
    )
    if (operations.length) onSave(operations)
    else onClose()
  }

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Edit tag</DialogTitle>
          <DialogDescription>{usage(tag)} use this tag.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4 p-6">
          <FormField htmlFor="tag-name" label="Name" required>
            <Input
              id="tag-name"
              onChange={(e) => setName(e.target.value)}
              value={name}
            />
          </FormField>
          <FormField htmlFor="tag-description" label="Description">
            <Textarea
              id="tag-description"
              onChange={(e) => setDescription(e.target.value)}
              value={description}
            />
          </FormField>
          <LabelSwatchPicker
            label="Tag color"
            onChange={setColor}
            value={color}
          />
        </div>
        <DialogFooter>
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
          <Button disabled={isSaving || !name.trim()} onClick={save}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function MergeTagDialog({
  isSaving,
  onClose,
  onMerge,
  tag,
  tags,
}: {
  isSaving: boolean
  onClose: () => void
  onMerge: (target: string) => void
  tag: Tag
  tags: Tag[]
}) {
  const targets = tags.filter((t) => t.slug !== tag.slug)
  const [target, setTarget] = useState('')
  const targetName = targets.find((t) => t.slug === target)?.name

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Merge &quot;{tag.name}&quot;</DialogTitle>
          <DialogDescription>
            The {usage(tag)} that use this tag will use the target tag. Then
            &quot;{tag.name}&quot; is deleted. This action cannot be undone.
          </DialogDescription>
        </DialogHeader>
        <div className="p-6">
          <FormField htmlFor="merge-target" label="Merge into">
            <Select onValueChange={setTarget} value={target}>
              <SelectTrigger aria-label="Merge into" id="merge-target">
                <SelectValue placeholder="Select a tag" />
              </SelectTrigger>
              <SelectContent>
                {targets.map((t) => (
                  <SelectItem key={t.slug} value={t.slug}>
                    {t.name} ({t.slug})
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <DialogFooter>
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
          <Button
            disabled={isSaving || !target}
            onClick={() => onMerge(target)}
            variant="destructive"
          >
            {targetName ? `Merge into "${targetName}"` : 'Merge'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function usage(t: Tag): string {
  const plural = (n: number, word: string) =>
    `${n} ${word}${n === 1 ? '' : 's'}`
  return `${plural(documentCount(t), 'document')} and ${plural(agentCount(t), 'agent')}`
}
