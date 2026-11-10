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
import { ErrorBanner } from '@/components/ui/error-banner'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useOrganization } from '@/contexts/OrganizationContext'

import { Field, SchemaEditor } from './controls'
import { jsonObject, type ObjectSchema } from './schema'
import {
  changedFields,
  type SecretProvider,
  type SecretProviderType,
} from './types'

const NAME = /^[a-z0-9][a-z0-9_-]{0,99}$/

interface ProviderDialogProps {
  error?: unknown
  isPending: boolean
  onClose: () => void
  onSubmit: (body: Record<string, unknown>) => void
  /** The provider to edit. The dialog then sends only the changed fields. */
  original?: SecretProvider
  types: SecretProviderType[]
}

/** The create or edit dialog for a provider. */
// fallow-ignore-next-line complexity
export function ProviderDialog({
  error,
  isPending,
  onClose,
  onSubmit,
  original,
  types,
}: ProviderDialogProps) {
  const { selectedOrganization } = useOrganization()
  const [name, setName] = useState(original?.name ?? '')
  const [type, setType] = useState(original?.type ?? '')
  const [config, setConfig] = useState(
    original ? JSON.stringify(original.config, null, 2) : '{}',
  )
  const providerType = types.find((t) => t.type === type)
  const label = providerType?.label ?? type
  const schema = providerType?.config_schema as null | ObjectSchema | undefined
  // An empty schema: the type takes no configuration.
  const noConfig = !!schema && !Object.keys(schema.properties ?? {}).length
  const parsed = jsonObject(config)
  const nameError =
    name && !NAME.test(name)
      ? 'Use lower case letters, digits, - and _, starting with a letter or digit.'
      : undefined
  const ready = NAME.test(name) && !!type && (noConfig || !!parsed)

  const submit = () => {
    const body = { config: noConfig ? {} : parsed, name }
    if (!original) return onSubmit({ ...body, type })
    const changed = changedFields(body, original)
    if (!Object.keys(changed).length) return onClose()
    onSubmit(changed)
  }

  return (
    <Dialog onOpenChange={(open) => !open && onClose()} open>
      <DialogContent className="max-w-180">
        <DialogHeader>
          <DialogTitle>
            {original ? 'Edit provider' : 'New provider'}
          </DialogTitle>
          <DialogDescription>
            An adapter to an external secret system. The configuration holds no
            credentials: imbi-api uses its workload identity.
          </DialogDescription>
        </DialogHeader>
        <div className="max-h-[65vh] space-y-5 overflow-y-auto p-6">
          {error != null && (
            <ErrorBanner error={error} title="Failed to save the provider" />
          )}
          <div className="grid grid-cols-2 gap-4">
            <Field
              help={nameError ?? 'Bindings show this name.'}
              htmlFor="provider-name"
              label="Name"
              required
            >
              <Input
                aria-invalid={!!nameError}
                className="font-mono"
                id="provider-name"
                onChange={(e) => setName(e.target.value)}
                placeholder="aws-prod"
                value={name}
              />
            </Field>
            <Field htmlFor="provider-type" label="Type" required>
              {original ? (
                <p className="text-sm" id="provider-type">
                  {label}
                </p>
              ) : (
                <Select
                  onValueChange={(value) => {
                    setType(value)
                    setConfig('{}')
                  }}
                  value={type}
                >
                  <SelectTrigger aria-label="Type" id="provider-type">
                    <SelectValue placeholder="Select a type" />
                  </SelectTrigger>
                  <SelectContent>
                    {types.map((t) => (
                      <SelectItem key={t.type} value={t.type}>
                        {t.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          </div>
          {type &&
            (noConfig ? (
              <p className="border-tertiary bg-tertiary text-secondary rounded-lg border px-3.5 py-2.5 text-sm">
                {label} takes no configuration.
                {providerType?.credential_classes.includes('dynamic') &&
                  !providerType.credential_classes.includes('static') &&
                  ' Its credentials come from the identity source on the Identity tab.'}
              </p>
            ) : (
              <SchemaEditor
                hint={`how imbi-api connects to ${label}`}
                id="provider-config"
                label="Configuration"
                onChange={setConfig}
                schema={schema}
                text={config}
              />
            ))}
          {type === 'aws_secrets_manager' && selectedOrganization && (
            <p className="text-secondary text-xs">
              The role trust policy must require{' '}
              <span className="text-primary font-mono">
                sts:ExternalId = imbi:{selectedOrganization.id}
              </span>
              . Imbi checks this when you save.
            </p>
          )}
        </div>
        <DialogFooter>
          <Button onClick={onClose} variant="outline">
            Cancel
          </Button>
          <Button disabled={isPending || !ready} onClick={submit}>
            {original ? 'Save' : 'Create provider'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
