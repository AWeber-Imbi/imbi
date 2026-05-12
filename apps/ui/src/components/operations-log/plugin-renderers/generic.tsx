import { ShieldCheck } from 'lucide-react'

import type { PluginOpsLogContext } from './types'

const HIDDEN_KEYS = new Set(['action', 'plugin_slug', 'summary'])

export function GenericPluginPayload({ payload }: PluginOpsLogContext) {
  const isSecret = payload.secret === true
  const entries = Object.entries(payload).filter(
    ([key]) => !HIDDEN_KEYS.has(key),
  )
  if (entries.length === 0) {
    return (
      <p className="text-sm text-tertiary">No additional payload fields.</p>
    )
  }
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      {entries.map(([key, value]) => (
        <PayloadRow
          fieldKey={key}
          key={key}
          mask={isSecret && key === 'value'}
          value={value}
        />
      ))}
    </dl>
  )
}

function formatValue(value: unknown): string {
  if (value === null) return 'null'
  if (value === undefined) return ''
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean')
    return String(value)
  return JSON.stringify(value)
}

function PayloadRow({
  fieldKey,
  mask,
  value,
}: {
  fieldKey: string
  mask: boolean
  value: unknown
}) {
  return (
    <>
      <dt className="font-mono text-xs text-tertiary">{fieldKey}</dt>
      <dd className="flex items-center gap-1.5 break-words font-mono text-xs text-primary">
        {mask ? (
          <>
            <ShieldCheck className="h-3.5 w-3.5 text-tertiary" />
            <span>••••••</span>
          </>
        ) : (
          formatValue(value)
        )}
      </dd>
    </>
  )
}
