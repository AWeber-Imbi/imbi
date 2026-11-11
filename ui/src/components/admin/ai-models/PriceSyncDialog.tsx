import { useState } from 'react'

import { useMutation, useQuery } from '@tanstack/react-query'
import { ArrowRight, RefreshCw } from 'lucide-react'

import { applyAIModelPrices, previewAIModelPrices } from '@/api/endpoints'
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
import { extractApiErrorDetail } from '@/lib/apiError'
import type { AIPriceSyncApplyResult, AIPriceSyncModel } from '@/types'

const FIELD_LABELS: Record<string, string> = {
  cache_read_cost_per_million: 'Cache read',
  cache_write_cost_per_million: 'Cache write',
  input_cost_per_million: 'Input',
  output_cost_per_million: 'Output',
}

interface PriceSyncDialogProps {
  onApplied: (result: AIPriceSyncApplyResult) => void
  onClose: () => void
}

export function PriceSyncDialog({ onApplied, onClose }: PriceSyncDialogProps) {
  const [overwrite, setOverwrite] = useState<Set<string>>(new Set())

  // Each open downloads the price file once; never refetch behind the
  // admin's back while they review the diff.
  const preview = useQuery({
    gcTime: 0,
    queryFn: previewAIModelPrices,
    queryKey: ['ai-model-price-sync'],
    refetchOnWindowFocus: false,
    retry: false,
    staleTime: Infinity,
  })
  const apply = useMutation({
    mutationFn: applyAIModelPrices,
    onSuccess: onApplied,
  })

  const changed = preview.data?.models ?? []
  const unmatched = preview.data?.unmatched ?? []
  const applicable = changed.filter(
    (model) => overwrite.has(model.id) || fillsMissing(model),
  )

  const toggle = (id: string) =>
    setOverwrite((current) => {
      const next = new Set(current)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      open
    >
      <DialogContent className="max-w-150">
        <DialogHeader>
          <DialogTitle>Sync prices from LiteLLM</DialogTitle>
          <DialogDescription>
            Imbi fills missing prices with the LiteLLM list prices (USD per 1M
            tokens). A set price changes only when you select overwrite for that
            model.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3 p-6">
          {preview.isPending && (
            <p className="text-tertiary py-8 text-center text-sm">
              Downloading the LiteLLM price file&hellip;
            </p>
          )}

          {preview.error != null && (
            <div className="border-tertiary bg-secondary space-y-3 rounded-md border p-4">
              <p className="text-tertiary text-sm">
                {extractApiErrorDetail(preview.error)}
              </p>
              <Button
                onClick={() => void preview.refetch()}
                size="sm"
                variant="outline"
              >
                <RefreshCw className="mr-1.5 size-3.5" />
                Try again
              </Button>
            </div>
          )}

          {apply.error != null && (
            <p className="text-destructive text-sm">
              {extractApiErrorDetail(apply.error)}
            </p>
          )}

          {preview.isSuccess && (
            <>
              <p className="text-tertiary text-xs">
                {changed.length} to update, {preview.data.up_to_date} up to
                date, {unmatched.length} not in LiteLLM
                {unmatched.length > 0 && `: ${unmatched.join(', ')}`}
              </p>
              <div className="divide-tertiary max-h-96 divide-y overflow-y-auto">
                {changed.map((model) => (
                  <ModelDiff
                    key={model.id}
                    model={model}
                    onToggle={() => toggle(model.id)}
                    overwrite={overwrite.has(model.id)}
                  />
                ))}
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          <Button onClick={onClose} variant="ghost">
            Cancel
          </Button>
          <Button
            disabled={applicable.length === 0 || apply.isPending}
            onClick={() =>
              apply.mutate({
                models: applicable.map((model) => ({
                  id: model.id,
                  overwrite: overwrite.has(model.id),
                })),
              })
            }
          >
            Apply to {applicable.length} model
            {applicable.length === 1 ? '' : 's'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function fillsMissing(model: AIPriceSyncModel): boolean {
  return model.fields.some((field) => field.current === null)
}

function formatPrice(value: null | string): string {
  return value === null ? '—' : `$${value}`
}

function ModelDiff({
  model,
  onToggle,
  overwrite,
}: {
  model: AIPriceSyncModel
  onToggle: () => void
  overwrite: boolean
}) {
  const hasSetPrices = model.fields.some((field) => field.current !== null)
  return (
    <div className="space-y-1.5 py-2">
      <div className="flex items-center gap-3">
        <span className="min-w-0 flex-1">
          <span className="text-primary block text-sm font-medium">
            {model.name}
          </span>
          <span className="text-tertiary block truncate font-mono text-xs">
            {model.provider_name} · {model.litellm_key}
          </span>
        </span>
        {hasSetPrices && (
          <label className="text-secondary flex items-center gap-2 text-xs">
            <Checkbox
              aria-label={`Overwrite set prices for ${model.name}`}
              checked={overwrite}
              onCheckedChange={onToggle}
            />
            Overwrite set prices
          </label>
        )}
      </div>
      {model.fields.map((field) => {
        const kept = field.current !== null && !overwrite
        return (
          <div
            className="text-secondary flex items-center gap-2 font-mono text-xs"
            key={field.field}
          >
            <span className="w-24 font-sans">{FIELD_LABELS[field.field]}</span>
            <span
              className={kept || field.current === null ? '' : 'line-through'}
            >
              {formatPrice(field.current)}
            </span>
            <ArrowRight className="text-tertiary size-3" />
            <span className={kept ? 'text-tertiary' : 'text-primary'}>
              {formatPrice(field.litellm)}
            </span>
            {kept && <span className="text-tertiary font-sans">kept</span>}
          </div>
        )
      })}
    </div>
  )
}
