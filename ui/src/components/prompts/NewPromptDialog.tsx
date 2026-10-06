import { useState } from 'react'

import { Button } from '@/components/ui/button'
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
import type { PromptCreate, PromptKind } from '@/types'

import { AIModelSelect } from './AIModelSelect'

const NAME = /^[a-z0-9][a-z0-9._-]*$/

export interface NewPromptDefaults {
  name?: string
  namespace?: string
  slug?: string
  type?: string
}

interface NewPromptDialogProps {
  /** Prefilled values. */
  defaults?: NewPromptDefaults
  /** When true, the prefilled fields cannot be changed. */
  locked?: boolean
  namespaces: string[]
  onClose: () => void
  onSubmit: (prompt: PromptCreate) => void
  open: boolean
  pending: boolean
}

export function NewPromptDialog({
  defaults,
  locked = false,
  namespaces,
  onClose,
  onSubmit,
  open,
  pending,
}: NewPromptDialogProps) {
  const [namespace, setNamespace] = useState(defaults?.namespace ?? '')
  const [name, setName] = useState(defaults?.name ?? '')
  const [slug, setSlug] = useState(defaults?.slug ?? '')
  const [type, setType] = useState(defaults?.type ?? '')
  const isLocked = (field: keyof NewPromptDefaults) =>
    locked && defaults?.[field] !== undefined
  const [defaultLabel, setDefaultLabel] = useState('stable')
  const [kind, setKind] = useState<PromptKind>('generative')
  const [model, setModel] = useState<null | string>(null)

  const namespaceOk = NAME.test(namespace)
  const slugOk = slug === '' || NAME.test(slug)
  const labelOk = NAME.test(defaultLabel)
  const valid = namespaceOk && slugOk && labelOk && name.trim() !== ''

  const submit = () =>
    onSubmit({
      default_label: defaultLabel,
      kind,
      name: name.trim(),
      namespace,
      slug: slug || null,
      type: type.trim() || null,
      version: {
        messages: [],
        model,
        questions: {},
        state: '',
        system: '',
        tools: [],
        variable_schema: {},
      },
    })

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      open={open}
    >
      <DialogContent className="max-w-130">
        <DialogHeader>
          <DialogTitle>New prompt</DialogTitle>
          <DialogDescription>
            Consumers address it as namespace/slug@label. The default label
            points at version 1.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4 p-6">
          <FormField
            description="Groups related prompts, e.g. imbi-assistant."
            error={
              namespace && !namespaceOk
                ? 'Lowercase letters, digits, ".", "_" and "-" only'
                : undefined
            }
            htmlFor="prompt-namespace"
            label="Namespace"
            required
            touched
          >
            <Input
              className="font-mono"
              disabled={isLocked('namespace')}
              id="prompt-namespace"
              list="prompt-namespaces"
              onChange={(e) => setNamespace(e.target.value)}
              value={namespace}
            />
            <datalist id="prompt-namespaces">
              {namespaces.map((ns) => (
                <option key={ns} value={ns} />
              ))}
            </datalist>
          </FormField>
          <FormField htmlFor="prompt-name" label="Name" required>
            <Input
              disabled={isLocked('name')}
              id="prompt-name"
              onChange={(e) => setName(e.target.value)}
              value={name}
            />
          </FormField>
          <div className="grid grid-cols-2 gap-4">
            <FormField
              description="Derived from the name when empty."
              error={slugOk ? undefined : 'Not a valid slug'}
              htmlFor="prompt-slug"
              label="Slug"
              touched
            >
              <Input
                className="font-mono"
                disabled={isLocked('slug')}
                id="prompt-slug"
                onChange={(e) => setSlug(e.target.value)}
                value={slug}
              />
            </FormField>
            <FormField htmlFor="prompt-type" label="Type">
              <Input
                className="font-mono"
                disabled={isLocked('type')}
                id="prompt-type"
                onChange={(e) => setType(e.target.value)}
                placeholder="core_system"
                value={type}
              />
            </FormField>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <FormField
              error={labelOk ? undefined : 'Not a valid label'}
              htmlFor="prompt-default-label"
              label="Default label"
              required
              touched
            >
              <Input
                className="font-mono"
                id="prompt-default-label"
                onChange={(e) => setDefaultLabel(e.target.value)}
                value={defaultLabel}
              />
            </FormField>
            {/* A locked dialog seeds a known consumer prompt, which is
                generative. */}
            {!locked && (
              <FormField
                description={
                  kind === 'decision'
                    ? 'A state and typed questions for a decision model.'
                    : 'A system prompt and messages for a text model.'
                }
                label="Kind"
              >
                <Select
                  onValueChange={(next) => {
                    setKind(next as PromptKind)
                    setModel(null)
                  }}
                  value={kind}
                >
                  <SelectTrigger aria-label="Kind" className="font-mono">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="generative">generative</SelectItem>
                    <SelectItem value="decision">decision</SelectItem>
                  </SelectContent>
                </Select>
              </FormField>
            )}
          </div>
          <FormField label="Model">
            <AIModelSelect modelType={kind} onChange={setModel} value={model} />
          </FormField>
        </div>
        <DialogFooter>
          <Button onClick={onClose} size="sm" variant="ghost">
            Cancel
          </Button>
          <Button disabled={!valid || pending} onClick={submit} size="sm">
            Create prompt
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
