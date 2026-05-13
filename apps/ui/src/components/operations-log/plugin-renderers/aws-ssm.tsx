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
          <dt className="text-overline text-tertiary uppercase">Key</dt>
          <dd className="text-primary font-mono text-xs break-all">{key}</dd>
        </>
      )}
      {dataType && (
        <>
          <dt className="text-overline text-tertiary uppercase">Data type</dt>
          <dd className="text-primary font-mono text-xs">{dataType}</dd>
        </>
      )}
      <dt className="text-overline text-tertiary uppercase">Secret</dt>
      <dd className="text-primary flex items-center gap-1.5 text-xs">
        {isSecret ? (
          <>
            <ShieldCheck className="text-amber-text size-3.5" />
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
