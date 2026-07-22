import { useEffect, useMemo, useRef, useState } from 'react'

import { toast } from 'sonner'

import {
  createLoginProvider,
  setLoginProviderUsedAsLogin,
} from '@/api/endpoints'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { extractApiErrorDetail } from '@/lib/apiError'
import type { PluginOption, PluginPackage } from '@/types'

import { FieldDescription } from './integrations/FieldDescription'

interface AddAuthProviderDialogProps {
  onClose: () => void
  onCreated: () => void
  open: boolean
  plugins: PluginPackage[]
}

// Create a global login-provider integration and (optionally) promote it as
// the instance's SSO provider — all from the Auth Providers screen, skipping
// the separate Integrations create flow.
// fallow-ignore-next-line complexity
export function AddAuthProviderDialog({
  onClose,
  onCreated,
  open,
  plugins,
}: AddAuthProviderDialogProps) {
  const [pluginSlug, setPluginSlug] = useState(plugins[0]?.slug ?? '')
  const [credentials, setCredentials] = useState<Record<string, string>>({})
  const [options, setOptions] = useState<Record<string, unknown>>({})
  const [useForSignIn, setUseForSignIn] = useState(true)
  const [saving, setSaving] = useState(false)

  const plugin = useMemo(
    () => plugins.find((p) => p.slug === pluginSlug) ?? plugins[0] ?? null,
    [plugins, pluginSlug],
  )

  const selectPlugin = (nextSlug: string) => {
    setPluginSlug(nextSlug)
    const next = plugins.find((p) => p.slug === nextSlug)
    const seeded: Record<string, unknown> = {}
    for (const opt of next?.options ?? []) seeded[opt.name] = optionDefault(opt)
    setOptions(seeded)
    setCredentials({})
  }

  // Reset to a fresh form on each open: seed the first plugin's option
  // defaults (so an untouched submit still carries manifest defaults) and
  // clear any draft carried over from a previous open. Guarded on the
  // open transition so a background plugins refetch can't wipe live input.
  const wasOpen = useRef(false)
  useEffect(() => {
    if (open && !wasOpen.current) {
      const first = plugins[0]
      setPluginSlug(first?.slug ?? '')
      const seeded: Record<string, unknown> = {}
      for (const opt of first?.options ?? [])
        seeded[opt.name] = optionDefault(opt)
      setOptions(seeded)
      setCredentials({})
      setUseForSignIn(true)
    }
    wasOpen.current = open
  }, [open, plugins])

  const missingRequired =
    !plugin ||
    (plugin.credentials ?? []).some(
      (c) => c.required && !credentials[c.name]?.trim(),
    )

  const submit = async () => {
    if (!plugin || missingRequired) return
    const creds: Record<string, string> = {}
    for (const [key, value] of Object.entries(credentials)) {
      if (value.trim()) creds[key] = value
    }
    setSaving(true)
    try {
      // Login providers are one-per-plugin, so name/slug derive from the
      // plugin rather than being entered by hand.
      const created = await createLoginProvider({
        capabilities: { identity: { enabled: true, options: {} } },
        credentials: creds,
        name: plugin.name,
        options,
        plugin: plugin.slug,
        slug: plugin.slug,
        status: 'active',
      })
      if (useForSignIn) {
        await setLoginProviderUsedAsLogin(created.slug, true)
      }
      toast.success('Auth provider created')
      onCreated()
      onClose()
    } catch (err) {
      toast.error(`Failed to create provider: ${extractApiErrorDetail(err)}`)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next && !saving) onClose()
      }}
      open={open}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Add auth provider</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-4 p-6 pt-2">
          <p className="text-tertiary text-xs">
            Configure a login provider. The integration is created and, when
            enabled below, set as the instance's sign-in provider.
          </p>

          <div className="flex flex-col gap-1.5">
            <Label htmlFor="provider-plugin">Provider</Label>
            <Select onValueChange={selectPlugin} value={plugin?.slug ?? ''}>
              <SelectTrigger id="provider-plugin">
                <SelectValue placeholder="Select a provider" />
              </SelectTrigger>
              <SelectContent>
                {plugins.map((p) => (
                  <SelectItem key={p.slug} value={p.slug}>
                    {p.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {(plugin?.credentials ?? []).map((cred) => (
            <div className="flex flex-col gap-1.5" key={cred.name}>
              <Label htmlFor={`provider-cred-${cred.name}`}>
                {cred.label}{' '}
                <span
                  className={
                    cred.required
                      ? 'text-danger text-xs'
                      : 'text-tertiary text-xs'
                  }
                >
                  {cred.required ? 'required' : 'optional'}
                </span>
              </Label>
              <Input
                className="font-mono"
                id={`provider-cred-${cred.name}`}
                onChange={(e) =>
                  setCredentials((c) => ({ ...c, [cred.name]: e.target.value }))
                }
                type={cred.secret === false ? 'text' : 'password'}
                value={credentials[cred.name] ?? ''}
              />
              {cred.description && <FieldDescription text={cred.description} />}
            </div>
          ))}

          {(plugin?.options ?? []).map((opt) => (
            <ProviderOptionField
              key={opt.name}
              onChange={(value) =>
                setOptions((o) => ({ ...o, [opt.name]: value }))
              }
              option={opt}
              value={options[opt.name]}
            />
          ))}

          <label className="flex items-center gap-2.5">
            <Checkbox
              checked={useForSignIn}
              onCheckedChange={(v) => setUseForSignIn(v === true)}
            />
            <span className="text-primary text-sm">Use for sign-in now</span>
          </label>
        </div>
        <div className="border-tertiary flex items-center justify-end gap-2 border-t px-6 py-4">
          <Button onClick={onClose} variant="secondary">
            Cancel
          </Button>
          <Button
            className="bg-action text-action-foreground hover:bg-action-hover"
            disabled={saving || missingRequired}
            onClick={submit}
          >
            Create
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}

function optionDefault(opt: PluginOption): unknown {
  if (opt.default !== undefined && opt.default !== null) return opt.default
  if (opt.type === 'boolean') return false
  return ''
}

// fallow-ignore-next-line complexity
function ProviderOptionField({
  onChange,
  option,
  value,
}: {
  onChange: (value: unknown) => void
  option: PluginOption
  value: unknown
}) {
  if (option.type === 'boolean') {
    return (
      <label className="flex items-center gap-2.5">
        <Switch checked={value === true} onCheckedChange={onChange} />
        <span className="text-primary text-sm">{option.label}</span>
        {option.description && <FieldDescription text={option.description} />}
      </label>
    )
  }
  if (option.choices && option.choices.length > 0) {
    return (
      <div className="flex flex-col gap-1.5">
        <Label>{option.label}</Label>
        <Select
          onValueChange={onChange}
          value={typeof value === 'string' ? value : undefined}
        >
          <SelectTrigger>
            <SelectValue placeholder="Select…" />
          </SelectTrigger>
          <SelectContent>
            {option.choices.map((c) => (
              <SelectItem key={c} value={c}>
                {c}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {option.description && <FieldDescription text={option.description} />}
      </div>
    )
  }
  return (
    <div className="flex flex-col gap-1.5">
      <Label>{option.label}</Label>
      <Input
        onChange={(e) =>
          onChange(
            option.type === 'integer'
              ? e.target.value === ''
                ? null
                : Number(e.target.value)
              : e.target.value,
          )
        }
        type={
          option.type === 'integer'
            ? 'number'
            : option.type === 'secret'
              ? 'password'
              : 'text'
        }
        value={value === null || value === undefined ? '' : String(value)}
      />
      {option.description && <FieldDescription text={option.description} />}
    </div>
  )
}
