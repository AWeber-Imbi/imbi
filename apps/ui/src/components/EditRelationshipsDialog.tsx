import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Search } from 'lucide-react'

import { getProjects, setProjectRelationships } from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { useOrganization } from '@/contexts/OrganizationContext'
import type { ProjectRelationship } from '@/types'

interface EditRelationshipsDialogProps {
  isOpen: boolean
  onClose: () => void
  projectId: string
  projectName: string
  relationships: ProjectRelationship[]
}

export function EditRelationshipsDialog({
  isOpen,
  onClose,
  projectId,
  projectName,
  relationships,
}: EditRelationshipsDialogProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug || ''
  const queryClient = useQueryClient()
  const searchRef = useRef<HTMLInputElement>(null)

  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [hasInitialized, setHasInitialized] = useState(false)

  // Existing outbound dependency IDs
  const existingIds = useMemo(
    () =>
      new Set(
        relationships
          .filter((r) => r.direction === 'outbound')
          .map((r) => r.project.id),
      ),
    [relationships],
  )

  // Initialize selection from existing relationships when dialog opens
  useEffect(() => {
    if (isOpen && !hasInitialized) {
      setSelected(new Set(existingIds))
      setSearch('')
      mutation.reset()
      setHasInitialized(true)
    }
    if (!isOpen) {
      setHasInitialized(false)
    }
    // mutation.reset is called at most once per open; excluding `mutation` avoids
    // re-running this effect on every render (useMutation returns a new object).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, existingIds, hasInitialized])

  // Focus search on open
  useEffect(() => {
    if (isOpen) {
      const timer = setTimeout(() => searchRef.current?.focus(), 100)
      return () => clearTimeout(timer)
    }
  }, [isOpen])

  const {
    data: allProjects = [],
    isError,
    isLoading,
  } = useQuery({
    enabled: !!orgSlug && isOpen,
    queryFn: ({ signal }) => getProjects(orgSlug, signal),
    queryKey: ['projects', orgSlug],
  })

  // All projects except the current one, sorted alphabetically
  const candidates = useMemo(() => {
    return allProjects
      .filter((p) => p.id !== projectId)
      .sort((a, b) => a.name.localeCompare(b.name))
  }, [allProjects, projectId])

  // Filtered by search
  const filtered = useMemo(() => {
    if (!search.trim()) return candidates
    const q = search.toLowerCase()
    return candidates.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        p.slug.toLowerCase().includes(q) ||
        (p.project_types || []).some((pt) => pt.name.toLowerCase().includes(q)),
    )
  }, [candidates, search])

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  // Compute diff
  const added = useMemo(
    () => [...selected].filter((id) => !existingIds.has(id)),
    [selected, existingIds],
  )
  const removed = useMemo(
    () => [...existingIds].filter((id) => !selected.has(id)),
    [selected, existingIds],
  )
  const changeCount = added.length + removed.length

  const mutation = useMutation({
    mutationFn: () =>
      setProjectRelationships(orgSlug, projectId, [...selected]),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ['project-relationships', orgSlug, projectId],
      })
      onClose()
    },
  })

  const handleSave = () => {
    if (changeCount === 0) {
      onClose()
      return
    }
    mutation.mutate()
  }

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open={isOpen}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>Edit Relationships</DialogTitle>
          <DialogDescription>
            Select projects that <strong>{projectName}</strong> depends on.
          </DialogDescription>
        </DialogHeader>

        <div className="p-6">
          {/* Search */}
          <div className="relative">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400 dark:text-slate-500" />
            <Input
              className="pl-9"
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search projects..."
              ref={searchRef}
              type="text"
              value={search}
            />
          </div>

          {/* Project list */}
          <div className="-mx-6 mt-4 h-[400px] overflow-y-auto border-y px-6 py-1">
            {isLoading ? (
              <div className="flex items-center justify-center py-12">
                <div className="h-5 w-5 animate-spin rounded-full border-2 border-current border-t-transparent opacity-50" />
              </div>
            ) : isError ? (
              <p className="py-8 text-center text-sm text-red-600 dark:text-red-400">
                Failed to load projects. Please try again.
              </p>
            ) : filtered.length === 0 ? (
              <p className="py-8 text-center text-sm text-slate-500 dark:text-slate-400">
                {search
                  ? 'No projects match your search'
                  : 'No projects available'}
              </p>
            ) : (
              filtered.map((p) => {
                const isChecked = selected.has(p.id)
                const wasChecked = existingIds.has(p.id)
                const isChanged = isChecked !== wasChecked
                const typeLabel = (p.project_types || [])
                  .map((pt) => pt.name)
                  .join(', ')

                return (
                  <label
                    className={`flex cursor-pointer items-center gap-3 rounded-md px-2 py-2 transition-colors hover:bg-slate-50 dark:hover:bg-slate-700 ${
                      isChanged ? 'bg-amber-50 dark:bg-amber-900/30' : ''
                    }`}
                    key={p.id}
                  >
                    <Checkbox
                      checked={isChecked}
                      onCheckedChange={() => toggle(p.id)}
                    />
                    <span className="min-w-0 flex-1 truncate text-sm font-medium text-slate-900 dark:text-slate-100">
                      {p.name}
                    </span>
                    {typeLabel && (
                      <span className="flex-shrink-0 text-xs text-slate-400 dark:text-slate-500">
                        {typeLabel}
                      </span>
                    )}
                  </label>
                )
              })
            )}
          </div>
        </div>

        {/* Summary + actions */}
        <DialogFooter className="items-center gap-2 sm:justify-between">
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {changeCount > 0 ? (
              <>
                {added.length > 0 && (
                  <span className="text-green-600 dark:text-green-400">
                    +{added.length} added
                  </span>
                )}
                {added.length > 0 && removed.length > 0 && ', '}
                {removed.length > 0 && (
                  <span className="text-red-600 dark:text-red-400">
                    -{removed.length} removed
                  </span>
                )}
              </>
            ) : (
              <span>{selected.size} dependencies</span>
            )}
          </div>
          <div className="flex gap-2">
            <Button onClick={onClose} size="sm" variant="outline">
              Cancel
            </Button>
            <Button
              className="bg-action text-action-foreground hover:bg-action-hover"
              disabled={mutation.isPending}
              onClick={handleSave}
              size="sm"
            >
              {mutation.isPending
                ? 'Saving...'
                : changeCount > 0
                  ? `Save ${changeCount} change${changeCount !== 1 ? 's' : ''}`
                  : 'Done'}
            </Button>
          </div>
        </DialogFooter>

        {mutation.isError && (
          <p className="text-center text-sm text-red-600 dark:text-red-400">
            Failed to save. Please try again.
          </p>
        )}
      </DialogContent>
    </Dialog>
  )
}
