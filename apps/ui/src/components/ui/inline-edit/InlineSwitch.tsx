import { Switch } from '@/components/ui/switch'
import { toast } from 'sonner'

export interface InlineSwitchProps {
  value: boolean | null
  onCommit: (next: boolean) => Promise<void> | void
  readOnly?: boolean
  pending?: boolean
}

export function InlineSwitch({
  value,
  onCommit,
  readOnly = false,
  pending = false,
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
