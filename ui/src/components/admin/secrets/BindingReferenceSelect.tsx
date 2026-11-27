import { useQuery } from '@tanstack/react-query'

import { listSecretBindings, listSecretProviders } from '@/api/endpoints'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

import type { SecretBinding, SecretProvider } from './types'

// Radix Select refuses an empty item value.
const NONE = '__none__'

interface BindingReferenceSelectProps {
  disabled?: boolean
  /** The label of the "no binding" choice. */
  emptyLabel: string
  /** Which enabled bindings to offer; ``provider`` is the binding's own. */
  filter?: (binding: SecretBinding, provider?: SecretProvider) => boolean
  id?: string
  label: string
  onChange: (reference: null | string) => void
  orgSlug: string
  value: null | string
}

// A select of the organization's secret bindings. The value is the
// binding's secret:// reference. Only enabled bindings are offered: the
// broker refuses a disabled one.
export function BindingReferenceSelect({
  disabled,
  emptyLabel,
  filter = () => true,
  id,
  label,
  onChange,
  orgSlug,
  value,
}: BindingReferenceSelectProps) {
  const bindingsQuery = useQuery({
    queryFn: ({ signal }) => listSecretBindings(orgSlug, signal),
    queryKey: ['secret-bindings', orgSlug],
  })
  const providersQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviders(orgSlug, signal),
    queryKey: ['secret-providers', orgSlug],
  })
  const providers = new Map(
    (providersQuery.data ?? []).map((provider) => [provider.id, provider]),
  )
  const references = (bindingsQuery.data ?? [])
    .filter(
      (binding) =>
        binding.enabled && filter(binding, providers.get(binding.provider_id)),
    )
    .map((binding) => binding.reference)
  // Keep a saved value visible after its binding is gone or disabled.
  if (value && !references.includes(value)) references.push(value)

  return (
    <Select
      disabled={disabled}
      onValueChange={(next) => onChange(next === NONE ? null : next)}
      value={value ?? NONE}
    >
      <SelectTrigger aria-label={label} className="text-sm" id={id}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>{emptyLabel}</SelectItem>
        {references.map((reference) => (
          <SelectItem key={reference} value={reference}>
            {reference}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
