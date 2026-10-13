import { useQuery } from '@tanstack/react-query'

import { listSecretBindings, listSecretProviders } from '@/api/endpoints'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'

// Radix Select refuses an empty item value.
const NONE = '__none__'

interface GitHubAppBindingSelectProps {
  disabled?: boolean
  id?: string
  onChange: (reference: null | string) => void
  orgSlug: string
  value: null | string
}

// The agent editor field for a github_app secret binding (harness plan
// 5.3 and 9.8). The value is the binding's secret:// reference.
export function GitHubAppBindingSelect({
  disabled,
  id,
  onChange,
  orgSlug,
  value,
}: GitHubAppBindingSelectProps) {
  const bindingsQuery = useQuery({
    queryFn: ({ signal }) => listSecretBindings(orgSlug, signal),
    queryKey: ['secret-bindings', orgSlug],
  })
  const providersQuery = useQuery({
    queryFn: ({ signal }) => listSecretProviders(orgSlug, signal),
    queryKey: ['secret-providers', orgSlug],
  })
  const appProviders = new Set(
    (providersQuery.data ?? [])
      .filter((provider) => provider.type === 'github_app')
      .map((provider) => provider.id),
  )
  const references = (bindingsQuery.data ?? [])
    .filter((binding) => appProviders.has(binding.provider_id))
    .map((binding) => binding.reference)
  // Keep a saved value visible after its binding is gone.
  if (value && !references.includes(value)) references.push(value)

  return (
    <Select
      disabled={disabled}
      onValueChange={(next) => onChange(next === NONE ? null : next)}
      value={value ?? NONE}
    >
      <SelectTrigger
        aria-label="GitHub App binding"
        className="text-sm"
        id={id}
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NONE}>No GitHub App</SelectItem>
        {references.map((reference) => (
          <SelectItem key={reference} value={reference}>
            {reference}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
