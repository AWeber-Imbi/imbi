import { useState } from 'react'

import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type { Prompt, PromptVersion } from '@/types'

const NAME = /^[a-z0-9][a-z0-9._-]*$/

export interface PromoteValues {
  label: string
  makeDefault: boolean
  version: number
}

interface PromoteDialogProps {
  initialVersion: number
  onClose: () => void
  onSubmit: (values: PromoteValues) => void
  open: boolean
  pending: boolean
  prompt: Prompt
  versions: PromptVersion[]
}

export function PromoteDialog({
  initialVersion,
  onClose,
  onSubmit,
  open,
  pending,
  prompt,
  versions,
}: PromoteDialogProps) {
  const [label, setLabel] = useState(prompt.default_label)
  const [version, setVersion] = useState(initialVersion)
  const [makeDefault, setMakeDefault] = useState(false)
  const labelOk = NAME.test(label)
  const current = prompt.labels.find((l) => l.name === label)
  const isDefault = label === prompt.default_label

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      open={open}
    >
      <DialogContent className="max-w-120">
        <DialogHeader>
          <DialogTitle>Promote a version</DialogTitle>
          <DialogDescription>
            Every consumer of {prompt.ref}@{label || '…'} gets the version you
            pick here. No prompt body changes.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 p-6">
          <div className="grid grid-cols-2 gap-4">
            <FormField
              description={
                current ? `Now at v${current.version}` : 'Creates a new label'
              }
              error={labelOk ? undefined : 'Not a valid label'}
              htmlFor="promote-label"
              label="Label"
              required
              touched
            >
              <Input
                className="font-mono"
                id="promote-label"
                list="promote-labels"
                onChange={(e) => setLabel(e.target.value)}
                value={label}
              />
              <datalist id="promote-labels">
                {prompt.labels.map((l) => (
                  <option key={l.name} value={l.name} />
                ))}
              </datalist>
            </FormField>
            <FormField label="Version" required>
              <Select
                onValueChange={(v) => setVersion(Number(v))}
                value={String(version)}
              >
                <SelectTrigger aria-label="Version" className="font-mono">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {versions.map((v) => (
                    <SelectItem key={v.n} value={String(v.n)}>
                      v{v.n}
                      <span className="text-tertiary ml-2">
                        {v.content_sha256.slice(0, 8)}
                      </span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
          </div>
          {!isDefault && (
            <label className="text-secondary flex items-center gap-2 text-sm">
              <Checkbox
                checked={makeDefault}
                onCheckedChange={(v) => setMakeDefault(v === true)}
              />
              Make {label || 'this label'} the default label
            </label>
          )}
        </div>
        <DialogFooter>
          <Button onClick={onClose} size="sm" variant="ghost">
            Cancel
          </Button>
          <Button
            disabled={!labelOk || pending}
            onClick={() =>
              onSubmit({
                label,
                makeDefault: makeDefault && !isDefault,
                version,
              })
            }
            size="sm"
          >
            Promote
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
