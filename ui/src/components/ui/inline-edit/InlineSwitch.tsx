import type { ReactNode } from 'react'
import { useCallback } from 'react'

import { toast } from 'sonner'

import { Switch } from '@/components/ui/switch'
import { useInlineEdit } from '@/hooks/useInlineEdit'

import { InlineDisplay } from './InlineDisplay'

export interface InlineSwitchProps {
  onCommit: (next: boolean) => Promise<void> | void
  pending?: boolean
  readOnly?: boolean
  renderDisplay?: ReactNode
  value: boolean | null
}

export function InlineSwitch({
  onCommit,
  pending = false,
  readOnly = false,
  renderDisplay,
  value,
}: InlineSwitchProps) {
  const boolValue = value ?? false

  const handleCommit = useCallback(
    async (next: boolean) => {
      await onCommit(next)
    },
    [onCommit],
  )

  const edit = useInlineEdit<boolean>({
    initial: boolValue,
    onCommit: handleCommit,
  })

  if (!edit.isEditing) {
    return (
      <InlineDisplay
        hasValue={value !== null}
        onClick={edit.enter}
        pending={pending}
        readOnly={readOnly}
      >
        {renderDisplay ?? (
          <span className="text-sm">{boolValue ? 'True' : 'False'}</span>
        )}
      </InlineDisplay>
    )
  }

  return (
    <Switch
      autoFocus
      checked={edit.draft}
      disabled={pending}
      onBlur={edit.cancel}
      onCheckedChange={async (next) => {
        edit.setDraft(next)
        try {
          await onCommit(next)
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Save failed')
        } finally {
          edit.cancel()
        }
      }}
    />
  )
}
