import { useQuery } from '@tanstack/react-query'

import { listAIModels } from '@/api/endpoints'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'

// Radix Select reserves the empty string, so "no model" needs a sentinel.
const NONE = '__none__'

interface AIModelSelectProps {
  className?: string
  disabled?: boolean
  onChange: (slug: null | string) => void
  value: null | string
}

/**
 * Pick a generative model from the AI Models catalog, by slug. Prompt
 * versions hold text prompts, which decision models cannot run.
 */
export function AIModelSelect({
  className,
  disabled = false,
  onChange,
  value,
}: AIModelSelectProps) {
  const { data: models = [], isSuccess } = useQuery({
    queryFn: ({ signal }) => listAIModels(signal),
    queryKey: queryKeys.aiModels(),
  })
  // Until the catalog has loaded, a value cannot be judged unknown.
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
          <SelectItem value={value}>
            {isSuccess ? `${value} (not in catalog)` : value}
          </SelectItem>
        )}
        {models
          .filter(
            (m) =>
              m.model_type !== 'decision' && (m.enabled || m.slug === value),
          )
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
