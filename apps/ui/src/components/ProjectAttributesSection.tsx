import { memo, useCallback, useMemo } from 'react'
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

interface AttributeField {
  key: string
  label: string
  value: string | null
  rawValue: unknown
  title?: string
  uiMaps: XUiMaps
  def: ProjectSchemaSectionProperty
}

interface ProjectAttributeRowProps {
  field: AttributeField
  patch: (path: string, value: unknown) => Promise<void>
  pending: boolean
}

const LABEL_CLASS = 'text-tertiary'
const VALUE_CLASS = 'text-primary'
const MUTED_CLASS = 'text-tertiary'
const DIVIDER_CLASS = 'border-tertiary'

const ProjectAttributeRow = memo(function ProjectAttributeRow({
  field,
  patch,
  pending,
}: ProjectAttributeRowProps) {
  const {
    key,
    label: fieldLabel,
    value: fieldValue,
    rawValue,
    title: fieldTitle,
    uiMaps,
    def,
  } = field

  const handleCommit = useCallback(
    (v: unknown) => patch(`/${key}`, v),
    [patch, key],
  )

  const mappedColor = resolveColor(uiMaps, rawValue)
  const mappedIcon = resolveIcon(uiMaps, rawValue)
  const FieldIcon = mappedIcon ? getIcon(mappedIcon) : null
  const textColorClass = mappedColor
    ? (COLOR_TEXT[mappedColor] ?? VALUE_CLASS)
    : VALUE_CLASS
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
          <span className={`text-sm ${textColorClass}`}>{fieldValue}</span>
        )}
      </span>
    ) : null

  return (
    <div
      className={`flex items-center justify-between border-b py-1.5 ${DIVIDER_CLASS} last:border-0`}
    >
      <span className={`text-sm ${LABEL_CLASS}`}>{fieldLabel}</span>
      {editable ? (
        <InlineField
          def={def}
          raw={rawValue}
          onCommit={handleCommit}
          pending={pending}
          display={richDisplay}
        />
      ) : richDisplay !== null ? (
        richDisplay
      ) : (
        <span className={`text-sm italic ${MUTED_CLASS}`}>Not set</span>
      )}
    </div>
  )
})

export function ProjectAttributesSection({
  project,
  projectSchema,
  patch,
  pendingPath,
}: ProjectAttributesSectionProps) {
  const attributeFields = useMemo<AttributeField[]>(() => {
    if (!projectSchema) return []
    const seen = new Set<string>()
    const fields: AttributeField[] = []
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
      {attributeFields.map((field) => (
        <ProjectAttributeRow
          key={field.key}
          field={field}
          patch={patch}
          pending={pendingPath === `/${field.key}`}
        />
      ))}
    </>
  )
}
