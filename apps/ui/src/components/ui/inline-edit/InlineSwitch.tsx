import { useEffect, useState } from 'react'

import { toast } from 'sonner'

import { Switch } from '@/components/ui/switch'

export interface InlineSwitchProps {
  onCommit: (next: boolean) => Promise<void> | void
  pending?: boolean
  readOnly?: boolean
  value?: boolean
}

export function InlineSwitch({
  onCommit,
  pending = false,
  readOnly = false,
  value,
}: InlineSwitchProps) {
  const [checked, setChecked] = useState(value ?? false)

  useEffect(() => {
    setChecked(value ?? false)
  }, [value])

  return (
    <Switch
      checked={checked}
      disabled={pending || readOnly}
      onCheckedChange={async (next) => {
        setChecked(next)
        try {
          await onCommit(next)
        } catch (e) {
          setChecked(!next)
          toast.error(e instanceof Error ? e.message : 'Save failed')
        }
      }}
    />
  )
}
