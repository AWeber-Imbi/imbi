import { ShieldCheck } from 'lucide-react'

import type { PluginOpsLogContext, PluginOpsLogRenderer } from './types'

function details({ payload }: PluginOpsLogContext) {
  const key = readString(payload, 'key')
  const dataType = readString(payload, 'data_type')
  const isSecret = payload.secret === true
  return (
    <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
      {key && (
        <>
          <dt className="text-overline uppercase text-tertiary">Key</dt>
          <dd className="break-all font-mono text-xs text-primary">{key}</dd>
        </>
      )}
      {dataType && (
        <>
          <dt className="text-overline uppercase text-tertiary">Data type</dt>
          <dd className="font-mono text-xs text-primary">{dataType}</dd>
        </>
      )}
      <dt className="text-overline uppercase text-tertiary">Secret</dt>
      <dd className="flex items-center gap-1.5 text-xs text-primary">
        {isSecret ? (
          <>
            <ShieldCheck className="h-3.5 w-3.5 text-amber-text" />
            <span>Yes</span>
          </>
        ) : (
          <span>No</span>
        )}
      </dd>
    </dl>
  )
}

function label({ action, payload }: PluginOpsLogContext): string {
  const key = readString(payload, 'key')
  if (!key) {
    return action ? `aws-ssm · ${action}` : 'aws-ssm'
  }
  switch (action) {
    case 'delete_value':
      return `Deleted parameter "${key}"`
    case 'set_value':
      return `Set parameter "${key}"`
    default:
      return action ? `${action} "${key}"` : `aws-ssm "${key}"`
  }
}

function readString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key]
  return typeof value === 'string' ? value : ''
}

export const awsSsmRenderer: PluginOpsLogRenderer = {
  details,
  displayName: 'AWS SSM Parameter Store',
  label,
}
