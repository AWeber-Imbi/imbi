import { useMemo } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { Input } from '@/components/ui/input'
import { SavedIndicator } from '@/components/ui/saved-indicator'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { useEditableKeyValueMap } from '@/hooks/useEditableKeyValueMap'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import type { Environment } from '@/types'

type EnvFields = Record<string, string>

interface EditEnvironmentsCardProps {
  environments: Environment[]
  availableEnvironments: Environment[]
  onPatch: (envData: Record<string, EnvFields>) => Promise<void>
}

function toLabel(key: string): string {
  return key
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

function extractFields(env: Environment): EnvFields {
  const out: EnvFields = {}
  for (const [key, val] of Object.entries(env)) {
    if (ENVIRONMENT_BASE_FIELDS_SET.has(key)) continue
    out[key] = val != null ? String(val) : ''
  }
  return out
}

export function EditEnvironmentsCard({
  environments,
  availableEnvironments,
  onPatch,
}: EditEnvironmentsCardProps) {
  const serverMap = useMemo<Record<string, EnvFields>>(() => {
    const map: Record<string, EnvFields> = {}
    for (const env of environments) map[env.slug] = extractFields(env)
    return map
  }, [environments])

  const {
    drafts,
    setDraft,
    pendingDelete,
    requestDelete,
    cancelDelete,
    confirmDelete,
    saved,
    flash,
  } = useEditableKeyValueMap<EnvFields>({ serverMap, onPatch })

  const dynamicFields = useMemo(() => {
    const fieldSet = new Set<string>()
    for (const env of environments) {
      for (const key of Object.keys(env)) {
        if (!ENVIRONMENT_BASE_FIELDS_SET.has(key)) fieldSet.add(key)
      }
    }
    return [...fieldSet].sort()
  }, [environments])

  const envBySlug = useMemo(() => {
    const m = new Map<string, Environment>()
    for (const e of environments) m.set(e.slug, e)
    return m
  }, [environments])

  const currentSlugs = useMemo(
    () => new Set(environments.map((e) => e.slug)),
    [environments],
  )

  const unassignedEnvs = useMemo(
    () =>
      availableEnvironments
        .filter((e) => !currentSlugs.has(e.slug))
        .sort((a, b) => a.name.localeCompare(b.name)),
    [availableEnvironments, currentSlugs],
  )

  // Merge drafts on top of serverMap so a blur that races an in-flight PATCH
  // doesn't revive stale server values for concurrently-edited fields.
  const buildBaseline = (): Record<string, EnvFields> => {
    const out: Record<string, EnvFields> = {}
    for (const env of environments) {
      out[env.slug] = {
        ...serverMap[env.slug],
        ...(drafts[env.slug] ?? {}),
      }
    }
    return out
  }

  const handleFieldBlur = async (slug: string, field: string) => {
    const next = (drafts[slug]?.[field] ?? '').trim()
    const current = serverMap[slug]?.[field] ?? ''
    if (next === current) return
    const payload = buildBaseline()
    payload[slug] = { ...payload[slug], [field]: next }
    try {
      await onPatch(payload)
      flash(`${slug}:${field}`)
    } catch {
      // Parent surfaces the error; keep the draft for retry.
    }
  }

  const handleAdd = async (slug: string) => {
    if (!slug || currentSlugs.has(slug)) return
    const payload = buildBaseline()
    payload[slug] = {}
    try {
      await onPatch(payload)
    } catch {
      // Parent surfaces the error.
    }
  }

  const pendingEnv = pendingDelete ? envBySlug.get(pendingDelete) : undefined

  if (environments.length === 0 && unassignedEnvs.length === 0) return null

  return (
    <Card className="p-6">
      <h3 className="mb-4 text-primary">Environments</h3>

      <div className="divide-y divide-border">
        {environments.map((env) => (
          <div key={env.slug} className="flex gap-3 py-4 first:pt-0 last:pb-0">
            <div className="w-[15%] flex-shrink-0 pt-1">
              <EnvironmentBadge
                name={env.name}
                slug={env.slug}
                label_color={env.label_color}
              />
            </div>
            <div className="flex-1 space-y-2">
              {dynamicFields.length === 0 ? (
                <p className="text-xs text-tertiary">
                  No blueprint fields for this environment.
                </p>
              ) : (
                dynamicFields.map((field) => (
                  <div key={field} className="flex items-center gap-3">
                    <label
                      htmlFor={`env-${env.slug}-${field}`}
                      className="w-20 flex-shrink-0 text-xs font-medium text-tertiary"
                    >
                      {toLabel(field)}
                    </label>
                    <div className="relative flex-1">
                      <Input
                        id={`env-${env.slug}-${field}`}
                        value={drafts[env.slug]?.[field] ?? ''}
                        onChange={(e) =>
                          setDraft(env.slug, {
                            ...(drafts[env.slug] ?? {}),
                            [field]: e.target.value,
                          })
                        }
                        onBlur={() => handleFieldBlur(env.slug, field)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') {
                            e.preventDefault()
                            e.currentTarget.blur()
                          }
                        }}
                        placeholder={toLabel(field)}
                        className="pr-8 text-sm"
                      />
                      <SavedIndicator show={!!saved[`${env.slug}:${field}`]} />
                    </div>
                  </div>
                ))
              )}
            </div>
            <div className="flex-shrink-0 pt-1">
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={`Remove ${env.name} environment`}
                className="h-8 w-8 text-secondary hover:text-danger"
                onClick={() => requestDelete(env.slug)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          </div>
        ))}

        {unassignedEnvs.length > 0 && (
          <div className="flex items-center gap-3 pt-4">
            <div className="w-[15%] flex-shrink-0">
              <Select value="" onValueChange={handleAdd}>
                <SelectTrigger className="text-sm">
                  <SelectValue placeholder="Add environment…" />
                </SelectTrigger>
                <SelectContent>
                  {unassignedEnvs.map((env) => (
                    <SelectItem key={env.slug} value={env.slug}>
                      {env.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex-1" />
            <div className="h-8 w-8 flex-shrink-0" aria-hidden />
          </div>
        )}
      </div>

      <ConfirmDialog
        open={pendingDelete !== null}
        title={
          pendingEnv
            ? `Remove ${pendingEnv.name} environment?`
            : 'Remove environment?'
        }
        description="This will remove the environment from the project along with any environment-specific field values."
        confirmLabel="Remove"
        onConfirm={confirmDelete}
        onCancel={cancelDelete}
      />
    </Card>
  )
}
