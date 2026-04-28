import { toast } from 'sonner'

import { Switch } from '@/components/ui/switch'

export interface InlineSwitchProps {
  onCommit: (next: boolean) => Promise<void> | void
  pending?: boolean
  readOnly?: boolean
  value: boolean | null
}

export function InlineSwitch({
  onCommit,
  pending = false,
  readOnly = false,
  value,
}: InlineSwitchProps) {
  return (
    <Switch
      checked={!!value}
      disabled={readOnly || pending}
      onCheckedChange={async (next) => {
        try {
          await onCommit(next)
        } catch (e) {
          toast.error(e instanceof Error ? e.message : 'Save failed')
        }
      }}
    />
  )
}
