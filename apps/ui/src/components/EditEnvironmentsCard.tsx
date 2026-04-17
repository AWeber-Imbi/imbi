import { useState, useEffect, useMemo } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Card } from '@/components/ui/card'
import { EnvironmentBadge } from '@/components/ui/environment-badge'
import { ENVIRONMENT_BASE_FIELDS_SET } from '@/lib/constants'
import type { Environment } from '@/types'

interface EditEnvironmentsCardProps {
  environments: Environment[]
  isSaving: boolean
  onSave: (envData: Record<string, Record<string, string>>) => void
}

function toLabel(key: string): string {
  return key
    .split('_')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ')
}

export function EditEnvironmentsCard({
  environments,
  isSaving,
  onSave,
}: EditEnvironmentsCardProps) {
  const dynamicFields = useMemo(() => {
    const fieldSet = new Set<string>()
    for (const env of environments) {
      for (const key of Object.keys(env)) {
        if (!ENVIRONMENT_BASE_FIELDS_SET.has(key)) {
          fieldSet.add(key)
        }
      }
    }
    return [...fieldSet].sort()
  }, [environments])

  const [data, setData] = useState<Record<string, Record<string, string>>>({})

  useEffect(() => {
    const initial: Record<string, Record<string, string>> = {}
    for (const env of environments) {
      const fields: Record<string, string> = {}
      for (const key of dynamicFields) {
        const val = env[key]
        fields[key] = val != null ? String(val) : ''
      }
      initial[env.slug] = fields
    }
    setData(initial)
  }, [environments, dynamicFields])

  const updateField = (envSlug: string, field: string, value: string) => {
    setData((prev) => ({
      ...prev,
      [envSlug]: { ...prev[envSlug], [field]: value },
    }))
  }

  const handleSave = () => {
    const result: Record<string, Record<string, string>> = {}
    for (const env of environments) {
      result[env.slug] = data[env.slug] ?? {}
    }
    onSave(result)
  }

  if (dynamicFields.length === 0) return null

  return (
    <Card className="p-6">
      <h3 className="mb-4 text-primary">Environment Specific Details</h3>

      <div className="space-y-4">
        {environments.map((env) => (
          <div key={env.slug} className="flex gap-3">
            <div className="w-[15%] flex-shrink-0 pt-1">
              <EnvironmentBadge
                name={env.name}
                slug={env.slug}
                label_color={env.label_color}
              />
            </div>
            <div className="flex-1 space-y-2">
              {dynamicFields.map((field) => (
                <div key={field}>
                  <label className="mb-1 block text-xs font-medium text-tertiary">
                    {toLabel(field)}
                  </label>
                  <Input
                    value={data[env.slug]?.[field] ?? ''}
                    onChange={(e) =>
                      updateField(env.slug, field, e.target.value)
                    }
                    disabled={isSaving}
                    placeholder={toLabel(field)}
                    className="text-sm"
                  />
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-4 flex justify-end">
        <Button
          size="sm"
          className="bg-action text-action-foreground hover:bg-action-hover"
          onClick={handleSave}
          disabled={isSaving}
        >
          {isSaving ? 'Saving...' : 'Save'}
        </Button>
      </div>
    </Card>
  )
}
