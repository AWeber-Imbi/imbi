import { useMemo } from 'react'
import { getIcon } from '@/lib/icons'
import { resolveColor, resolveIcon } from '@/lib/ui-maps'
import type { XUiMaps } from '@/lib/ui-maps'
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from '@/components/ui/tooltip'
import type {
  ProjectSchemaResponse,
  ProjectSchemaSectionProperty,
} from '@/api/endpoints'
import { isFieldEditable } from '@/components/ui/inline-edit/field-policy'
import { InlineField } from '@/components/ui/inline-edit/InlineField'
import type { Project } from '@/types'
import {
  COLOR_TEXT,
  formatFieldKey,
  formatFieldValue,
  resolveFieldValue,
} from '@/lib/project-field-formatting'

interface ProjectAttributesSectionProps {
  project: Project
  projectSchema: ProjectSchemaResponse | undefined
  patch: (path: string, value: unknown) => Promise<void>
  pendingPath: string | null
}

export function ProjectAttributesSection({
  project,
  projectSchema,
  patch,
  pendingPath,
}: ProjectAttributesSectionProps) {
  const label = 'text-tertiary'
  const value = 'text-primary'
  const muted = 'text-tertiary'
  const divider = 'border-tertiary'

  const attributeFields = useMemo(() => {
    if (!projectSchema) return []
    const seen = new Set<string>()
    const fields: {
      key: string
      label: string
      value: string | null
      rawValue: unknown
      title?: string
      uiMaps: XUiMaps
      def: ProjectSchemaSectionProperty
    }[] = []
    for (const section of projectSchema.sections) {
      for (const [key, def] of Object.entries(section.properties)) {
        if (seen.has(key) || key === 'url') continue
        seen.add(key)
        const raw = resolveFieldValue(key, section, project)
        const isDate = def.format === 'date-time' || def.format === 'date'
        const xUi = def['x-ui']
        fields.push({
          key,
          label: def.title || formatFieldKey(key),
          value: formatFieldValue(raw, def),
          rawValue: raw,
          title:
            isDate && raw != null
              ? new Date(String(raw)).toLocaleString()
              : undefined,
          uiMaps: {
            colorMap: xUi?.['color-map'] ?? undefined,
            iconMap: xUi?.['icon-map'] ?? undefined,
            colorRange: xUi?.['color-range'] ?? undefined,
            iconRange: xUi?.['icon-range'] ?? undefined,
            colorAge: xUi?.['color-age'] ?? undefined,
            iconAge: xUi?.['icon-age'] ?? undefined,
          },
          def,
        })
      }
    }
    return fields.sort((a, b) => a.label.localeCompare(b.label))
  }, [projectSchema, project])

  return (
    <>
      {attributeFields.map(
        ({
          key,
          label: fieldLabel,
          value: fieldValue,
          rawValue,
          title: fieldTitle,
          uiMaps,
          def,
        }) => {
          const mappedColor = resolveColor(uiMaps, rawValue)
          const mappedIcon = resolveIcon(uiMaps, rawValue)
          const FieldIcon = mappedIcon ? getIcon(mappedIcon) : null
          const textColorClass = mappedColor
            ? (COLOR_TEXT[mappedColor] ?? value)
            : value
          const editable = isFieldEditable(key, def)
          const richDisplay =
            fieldValue !== null ? (
              <span className="flex items-center gap-1.5">
                {FieldIcon && (
                  <FieldIcon
                    className={`h-3.5 w-3.5 flex-shrink-0 ${textColorClass}`}
                  />
                )}
                {fieldTitle ? (
                  <TooltipProvider delayDuration={200}>
                    <Tooltip>
                      <TooltipTrigger asChild>
                        <span
                          className={`text-sm ${textColorClass} cursor-help underline decoration-dotted`}
                        >
                          {fieldValue}
                        </span>
                      </TooltipTrigger>
                      <TooltipContent>
                        <p>{fieldTitle}</p>
                      </TooltipContent>
                    </Tooltip>
                  </TooltipProvider>
                ) : (
                  <span className={`text-sm ${textColorClass}`}>
                    {fieldValue}
                  </span>
                )}
              </span>
            ) : null
          return (
            <div
              key={key}
              className={`flex items-center justify-between border-b py-1.5 ${divider} last:border-0`}
            >
              <span className={`text-sm ${label}`}>{fieldLabel}</span>
              {editable ? (
                <InlineField
                  def={def}
                  raw={rawValue}
                  onCommit={(v) => patch(`/${key}`, v)}
                  pending={pendingPath === `/${key}`}
                  display={richDisplay}
                />
              ) : richDisplay !== null ? (
                richDisplay
              ) : (
                <span className={`text-sm italic ${muted}`}>Not set</span>
              )}
            </div>
          )
        },
      )}
    </>
  )
}
