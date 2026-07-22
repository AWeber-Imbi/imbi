import { useMemo } from 'react'

import { EditableKeyValueMap } from '@/components/ui/EditableKeyValueMap'
import { useEditableKeyValueMap } from '@/hooks/useEditableKeyValueMap'
import { getIcon, useIconRegistryVersion } from '@/lib/icons'
import type { LinkDefinition } from '@/types'

interface EditLinksCardProps {
  /**
   * Slugs of integrations the project is connected to. An integration's
   * dashboard URL is mirrored into `links` keyed by the integration slug and
   * is managed from the Integrations card, so those keys are hidden here: they
   * never render as an editable link row and are never offered as a link type
   * to add. This keeps the two from colliding when an integration slug also
   * matches a link definition.
   */
  integrationSlugs?: Set<string>
  linkDefs: LinkDefinition[]
  links: Record<string, string>
  onPatch: (links: Record<string, string>) => Promise<void>
}

export function EditLinksCard({
  integrationSlugs,
  linkDefs,
  links,
  onPatch,
}: EditLinksCardProps) {
  useIconRegistryVersion()

  const serverMap = useMemo(() => links ?? {}, [links])

  const state = useEditableKeyValueMap<string>({
    normalizeValue: (v) => v.trim(),
    onPatch,
    serverMap,
    transformPatch: stripEmpty,
  })

  const defBySlug = useMemo(() => {
    const m = new Map<string, LinkDefinition>()
    for (const d of linkDefs) m.set(d.slug, d)
    return m
  }, [linkDefs])

  const isIntegrationKey = useMemo(
    () => (slug: string) => integrationSlugs?.has(slug) ?? false,
    [integrationSlugs],
  )

  const visibleKeys = useMemo(
    () =>
      Object.keys(serverMap)
        .filter((slug) => defBySlug.has(slug) && !isIntegrationKey(slug))
        .sort((a, b) =>
          defBySlug.get(a)!.name.localeCompare(defBySlug.get(b)!.name),
        ),
    [serverMap, defBySlug, isIntegrationKey],
  )

  const unassignedKeys = useMemo(() => {
    const visible = new Set(visibleKeys)
    return linkDefs
      .filter((d) => !visible.has(d.slug) && !isIntegrationKey(d.slug))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((d) => d.slug)
  }, [linkDefs, visibleKeys, isIntegrationKey])

  return (
    <EditableKeyValueMap
      deleteDialogDescription="This will remove the link from the project."
      getDeleteDialogTitle={(slug) =>
        slug ? `Remove ${defBySlug.get(slug)?.name ?? 'link'}?` : 'Remove link?'
      }
      getNewValuePlaceholder={(slug) =>
        (slug && defBySlug.get(slug)?.url_template) || 'https://...'
      }
      getRemoveAriaLabel={(slug) =>
        `Remove ${defBySlug.get(slug)?.name ?? 'link'} link`
      }
      getValuePlaceholder={(slug) =>
        defBySlug.get(slug)?.url_template || 'https://...'
      }
      newKeyPlaceholder="Pick Link Type to Add"
      renderKeyLabel={(slug) => {
        const def = defBySlug.get(slug)!
        const Icon = getIcon(def.icon)
        return (
          <div className="text-secondary flex w-[15%] shrink-0 items-center gap-2">
            <Icon className="size-4 shrink-0" />
            <span className="truncate text-sm">{def.name}</span>
          </div>
        )
      }}
      renderSelectItem={(slug) => {
        const def = defBySlug.get(slug)!
        const Icon = getIcon(def.icon)
        return (
          <span className="flex items-center gap-2">
            <Icon className="size-4" />
            {def.name}
          </span>
        )
      }}
      renderSelectTrigger={(slug) => {
        const def = defBySlug.get(slug)
        if (!def) return null
        const Icon = getIcon(def.icon)
        return (
          <div className="text-secondary flex min-w-0 items-center gap-2">
            <Icon className="size-4 shrink-0" />
            <span className="truncate">{def.name}</span>
          </div>
        )
      }}
      state={state}
      title="Links"
      unassignedKeys={unassignedKeys}
      valueInputClassName="text-sm"
      valueInputType="url"
      visibleKeys={visibleKeys}
    />
  )
}

function stripEmpty(map: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(map)) {
    const t = (v ?? '').trim()
    if (t) out[k] = t
  }
  return out
}
