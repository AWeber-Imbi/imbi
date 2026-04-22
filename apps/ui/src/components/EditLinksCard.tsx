import { useMemo } from 'react'
import { getIcon } from '@/lib/icons'
import { EditableKeyValueMap } from '@/components/ui/EditableKeyValueMap'
import { useEditableKeyValueMap } from '@/hooks/useEditableKeyValueMap'
import type { LinkDefinition } from '@/types'

interface EditLinksCardProps {
  linkDefs: LinkDefinition[]
  links: Record<string, string>
  onPatch: (links: Record<string, string>) => Promise<void>
}

function stripEmpty(map: Record<string, string>): Record<string, string> {
  const out: Record<string, string> = {}
  for (const [k, v] of Object.entries(map)) {
    const t = (v ?? '').trim()
    if (t) out[k] = t
  }
  return out
}

export function EditLinksCard({
  linkDefs,
  links,
  onPatch,
}: EditLinksCardProps) {
  const serverMap = useMemo(() => links ?? {}, [links])

  const state = useEditableKeyValueMap<string>({
    serverMap,
    onPatch,
    normalizeValue: (v) => v.trim(),
    transformPatch: stripEmpty,
  })

  const defBySlug = useMemo(() => {
    const m = new Map<string, LinkDefinition>()
    for (const d of linkDefs) m.set(d.slug, d)
    return m
  }, [linkDefs])

  const visibleKeys = useMemo(
    () =>
      Object.keys(serverMap)
        .filter((slug) => defBySlug.has(slug))
        .sort((a, b) =>
          defBySlug.get(a)!.name.localeCompare(defBySlug.get(b)!.name),
        ),
    [serverMap, defBySlug],
  )

  const unassignedKeys = useMemo(() => {
    const visible = new Set(visibleKeys)
    return linkDefs
      .filter((d) => !visible.has(d.slug))
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((d) => d.slug)
  }, [linkDefs, visibleKeys])

  return (
    <EditableKeyValueMap
      state={state}
      title="Links"
      visibleKeys={visibleKeys}
      unassignedKeys={unassignedKeys}
      valueInputClassName="text-sm"
      valueInputType="url"
      renderKeyLabel={(slug) => {
        const def = defBySlug.get(slug)!
        const Icon = getIcon(def.icon)
        return (
          <div className="flex w-[15%] flex-shrink-0 items-center gap-2 text-secondary">
            <Icon className="h-4 w-4 flex-shrink-0" />
            <span className="truncate text-sm">{def.name}</span>
          </div>
        )
      }}
      renderSelectTrigger={(slug) => {
        const def = defBySlug.get(slug)
        if (!def) return null
        const Icon = getIcon(def.icon)
        return (
          <div className="flex min-w-0 items-center gap-2 text-secondary">
            <Icon className="h-4 w-4 flex-shrink-0" />
            <span className="truncate">{def.name}</span>
          </div>
        )
      }}
      renderSelectItem={(slug) => {
        const def = defBySlug.get(slug)!
        const Icon = getIcon(def.icon)
        return (
          <span className="flex items-center gap-2">
            <Icon className="h-4 w-4" />
            {def.name}
          </span>
        )
      }}
      getValuePlaceholder={(slug) =>
        defBySlug.get(slug)?.url_template || 'https://...'
      }
      getNewValuePlaceholder={(slug) =>
        (slug && defBySlug.get(slug)?.url_template) || 'https://...'
      }
      newKeyPlaceholder="Pick Link Type to Add"
      getRemoveAriaLabel={(slug) =>
        `Remove ${defBySlug.get(slug)?.name ?? 'link'} link`
      }
      getDeleteDialogTitle={(slug) =>
        slug ? `Remove ${defBySlug.get(slug)?.name ?? 'link'}?` : 'Remove link?'
      }
      deleteDialogDescription="This will remove the link from the project."
    />
  )
}
