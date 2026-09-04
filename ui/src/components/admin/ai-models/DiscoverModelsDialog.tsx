import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { RefreshCw, Search } from 'lucide-react'

import { discoverAIModels } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
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
import { extractApiErrorDetail } from '@/lib/apiError'
import { cn } from '@/lib/utils'
import type { AIDiscoveredModel, AIModelImport, AIProvider } from '@/types'

interface DiscoverModelsDialogProps {
  importError?: unknown
  isImporting: boolean
  onClose: () => void
  onImport: (models: AIModelImport[]) => void
  open: boolean
  orgSlug: string
  provider: AIProvider
}

export function DiscoverModelsDialog({
  importError,
  isImporting,
  onClose,
  onImport,
  open,
  orgSlug,
  provider,
}: DiscoverModelsDialogProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [searchQuery, setSearchQuery] = useState('')

  // Each open runs one discovery call. It is an outbound request with
  // the provider's key, so never refetch it behind the admin's back.
  const discovery = useQuery({
    gcTime: 0,
    queryFn: () => discoverAIModels(orgSlug, provider.id),
    queryKey: ['ai-model-discovery', orgSlug, provider.id],
    refetchOnMount: 'always',
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Infinity,
  })

  const models = useMemo(
    () => discovery.data?.models ?? [],
    [discovery.data?.models],
  )
  const newModels = models.filter((model) => !model.already_configured)
  const visible = models.filter((model) => matchesQuery(model, searchQuery))
  const allNewSelected =
    newModels.length > 0 && newModels.every((m) => selected.has(m.model_id))

  const toggle = (modelId: string) =>
    setSelected((current) => {
      const next = new Set(current)
      if (next.has(modelId)) next.delete(modelId)
      else next.add(modelId)
      return next
    })

  const toggleAllNew = () =>
    setSelected(
      allNewSelected
        ? new Set()
        : new Set(newModels.map((model) => model.model_id)),
    )

  const handleImport = () =>
    onImport(
      newModels
        .filter((model) => selected.has(model.model_id))
        .map((model) => ({
          context_window: model.context_window,
          display_name: model.display_name,
          max_output_tokens: model.max_output_tokens,
          model_id: model.model_id,
        })),
    )

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      open={open}
    >
      <DialogContent className="max-w-150">
        <DialogHeader>
          <DialogTitle>Discover models from {provider.name}</DialogTitle>
          <DialogDescription>
            Imbi asked {provider.name} for the models it serves. Pick the ones
            to add to this organization&rsquo;s catalog.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 p-6">
          {discovery.isPending && (
            <p className="text-tertiary py-8 text-center text-sm">
              Contacting {provider.name}&hellip;
            </p>
          )}

          {discovery.error != null && (
            <div className="border-tertiary bg-secondary space-y-3 rounded-md border p-4">
              <div className="text-primary text-sm font-medium">
                Could not reach {provider.name}
              </div>
              <p className="text-tertiary text-sm">
                {extractApiErrorDetail(discovery.error)}
              </p>
              <Button
                onClick={() => void discovery.refetch()}
                size="sm"
                variant="outline"
              >
                <RefreshCw className="mr-1.5 size-3.5" />
                Try again
              </Button>
            </div>
          )}

          {importError != null && (
            <p className="text-destructive text-sm">
              {extractApiErrorDetail(importError)}
            </p>
          )}

          {discovery.isSuccess && models.length === 0 && (
            <p className="text-tertiary py-8 text-center text-sm">
              {provider.name} reported no models.
            </p>
          )}

          {discovery.isSuccess && models.length > 0 && (
            <>
              <div className="flex items-center gap-3">
                <div className="relative flex-1">
                  <Search className="text-tertiary absolute top-1/2 left-3 size-4 -translate-y-1/2" />
                  <Input
                    aria-label="Search discovered models"
                    className="pl-10"
                    onChange={(e) => setSearchQuery(e.target.value)}
                    placeholder="Search models…"
                    value={searchQuery}
                  />
                </div>
                <Button
                  disabled={newModels.length === 0}
                  onClick={toggleAllNew}
                  size="sm"
                  variant="outline"
                >
                  {allNewSelected ? 'Clear selection' : 'Select all new'}
                </Button>
              </div>

              <div className="divide-tertiary max-h-80 divide-y overflow-y-auto">
                {visible.map((model) => (
                  <label
                    className={cn(
                      'flex items-center gap-3 py-2',
                      model.already_configured && 'opacity-55',
                    )}
                    key={model.model_id}
                  >
                    <Checkbox
                      aria-label={model.display_name}
                      checked={selected.has(model.model_id)}
                      disabled={model.already_configured}
                      onCheckedChange={() => toggle(model.model_id)}
                    />
                    <span className="min-w-0 flex-1">
                      <span className="text-primary block text-sm font-medium">
                        {model.display_name}
                      </span>
                      <span className="text-tertiary block truncate font-mono text-xs">
                        {model.model_id}
                      </span>
                    </span>
                    {model.already_configured && (
                      <Badge variant="neutral">Already configured</Badge>
                    )}
                  </label>
                ))}
                {visible.length === 0 && (
                  <p className="text-tertiary py-6 text-center text-sm">
                    No models match that search.
                  </p>
                )}
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <button
            className="text-secondary hover:text-primary text-sm font-medium"
            onClick={onClose}
            type="button"
          >
            Cancel
          </button>
          <button
            className="bg-action text-action-foreground hover:bg-action-hover rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50"
            disabled={selected.size === 0 || isImporting}
            onClick={handleImport}
            type="button"
          >
            Import {selected.size} model{selected.size === 1 ? '' : 's'}
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function matchesQuery(model: AIDiscoveredModel, query: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  return (
    model.display_name.toLowerCase().includes(q) ||
    model.model_id.toLowerCase().includes(q)
  )
}
