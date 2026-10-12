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

import type { ManualInput } from './runs'

type Inputs = Record<string, boolean | number | string>

/** Ask for the inputs that the manual trigger declares, then start. */
export function StartRunDialog({
  inputs,
  onClose,
  onStart,
  open,
  pending,
}: {
  inputs: ManualInput[]
  onClose: () => void
  onStart: (values: Inputs) => void
  open: boolean
  pending: boolean
}) {
  const [values, setValues] = useState<Record<string, boolean | string>>({})
  const set = (name: string, value: boolean | string) =>
    setValues((v) => ({ ...v, [name]: value }))
  const typed: Inputs = Object.fromEntries(
    inputs.map((i) => {
      const value = values[i.name]
      if (i.type === 'boolean') return [i.name, value === true]
      if (i.type === 'number') return [i.name, Number(value)]
      return [i.name, typeof value === 'string' ? value : '']
    }),
  )
  // Every declared input is required (the API refuses a run without it).
  const missing = inputs.some(
    (i) =>
      i.type !== 'boolean' &&
      (values[i.name] === undefined ||
        String(values[i.name]).trim() === '' ||
        Number.isNaN(typed[i.name])),
  )

  return (
    <Dialog onOpenChange={(next) => !next && onClose()} open={open}>
      <DialogContent>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            onStart(typed)
          }}
        >
          <DialogHeader>
            <DialogTitle>Run workflow</DialogTitle>
            <DialogDescription>
              The run uses the active version and acts for real.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-4 p-6">
            {inputs.map((input) => {
              const id = `workflow-run-input-${input.name}`
              return input.type === 'boolean' ? (
                <label className="flex items-center gap-2 text-sm" key={id}>
                  <Checkbox
                    checked={values[input.name] === true}
                    id={id}
                    onCheckedChange={(checked) =>
                      set(input.name, checked === true)
                    }
                  />
                  <span className="font-mono">{input.name}</span>
                </label>
              ) : (
                <FormField htmlFor={id} key={id} label={input.name} required>
                  <Input
                    id={id}
                    onChange={(e) => set(input.name, e.target.value)}
                    required
                    type={input.type === 'number' ? 'number' : 'text'}
                    value={String(values[input.name] ?? '')}
                  />
                </FormField>
              )
            })}
          </div>
          <DialogFooter>
            <Button onClick={onClose} type="button" variant="ghost">
              Cancel
            </Button>
            <Button disabled={pending || missing} type="submit">
              Start run
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  )
}
