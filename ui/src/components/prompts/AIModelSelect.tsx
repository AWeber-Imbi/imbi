import { useQuery } from '@tanstack/react-query'

import { listAIModels } from '@/api/endpoints'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { cn } from '@/lib/utils'

// Radix Select reserves the empty string, so "no model" needs a sentinel.
const NONE = '__none__'

interface AIModelSelectProps {
  className?: string
  disabled?: boolean
  onChange: (slug: null | string) => void
  orgSlug: string
  value: null | string
}

/** Pick a model from the organization's AI Models catalog, by slug. */
export function AIModelSelect({
  className,
  disabled = false,
  onChange,
  orgSlug,
  value,
}: AIModelSelectProps) {
  const { data: models = [] } = useQuery({
    queryFn: ({ signal }) => listAIModels(orgSlug, signal),
    queryKey: ['ai-models', orgSlug],
  })
  const known = value == null || models.some((m) => m.slug === value)
  return (
    <Select
      disabled={disabled}
      onValueChange={(v) => onChange(v === NONE ? null : v)}
      value={value ?? NONE}
    >
      <SelectTrigger
        aria-label="Model"
        className={cn('h-8 font-mono text-xs', className)}
      >
        <SelectValue placeholder="Select a model" />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>No model</SelectItem>
        {!known && value != null && (
          <SelectItem value={value}>{value} (not in catalog)</SelectItem>
        )}
        {models
          .filter((m) => m.enabled || m.slug === value)
          .map((m) => (
            <SelectItem key={m.id} value={m.slug}>
              {m.slug}
              <span className="text-tertiary ml-2">{m.model_id}</span>
            </SelectItem>
          ))}
      </SelectContent>
    </Select>
  )
}
