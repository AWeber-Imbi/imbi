import { memo, useCallback, useMemo } from 'react'

import type {
  ProjectSchemaResponse,
  ProjectSchemaSectionProperty,
} from '@/api/endpoints'
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card'
import { isFieldEditable } from '@/components/ui/inline-edit/field-policy'
import { InlineField } from '@/components/ui/inline-edit/InlineField'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip'
import { getIcon } from '@/lib/icons'
import {
  COLOR_TEXT,
  formatFieldKey,
  formatFieldValue,
  resolveFieldValue,
} from '@/lib/project-field-formatting'
import { resolveColor, resolveIcon } from '@/lib/ui-maps'
import type { XUiMaps } from '@/lib/ui-maps'
import type { Project } from '@/types'

interface AttributeField {
  def: ProjectSchemaSectionProperty
  description?: string
  key: string
  label: string
  rawValue: unknown
  title?: string
  uiMaps: XUiMaps
  value: null | string
}

interface ProjectAttributeRowProps {
  field: AttributeField
  patch: (path: string, value: unknown) => Promise<void>
  pending: boolean
}

interface ProjectAttributesSectionProps {
  patch: (path: string, value: unknown) => Promise<void>
  pendingPath: null | string
  project: Project
  projectSchema: ProjectSchemaResponse | undefined
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
    def,
    description: fieldDescription,
    key,
    label: fieldLabel,
    rawValue,
    title: fieldTitle,
    uiMaps,
    value: fieldValue,
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
          <FieldIcon className={`size-3.5 shrink-0 ${textColorClass}`} />
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

  const labelNode = fieldDescription ? (
    <HoverCard openDelay={200}>
      <HoverCardTrigger asChild>
        <button
          className={`text-sm ${LABEL_CLASS} cursor-help bg-transparent p-0 text-left underline decoration-dotted`}
          type="button"
        >
          {fieldLabel}
        </button>
      </HoverCardTrigger>
      <HoverCardContent className="text-sm" side="top">
        {fieldDescription}
      </HoverCardContent>
    </HoverCard>
  ) : (
    <span className={`text-sm ${LABEL_CLASS}`}>{fieldLabel}</span>
  )

  return (
    <div
      className={`flex items-center justify-between border-b py-1.5 ${DIVIDER_CLASS} last:border-0`}
    >
      {labelNode}
      {editable ? (
        <InlineField
          def={def}
          display={richDisplay}
          onCommit={handleCommit}
          pending={pending}
          raw={rawValue}
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
  patch,
  pendingPath,
  project,
  projectSchema,
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
          def,
          description: def.description ?? undefined,
          key,
          label: def.title || formatFieldKey(key),
          rawValue: raw,
          title:
            isDate && raw != null
              ? new Date(String(raw)).toLocaleString()
              : undefined,
          uiMaps: {
            colorAge: xUi?.['color-age'] ?? undefined,
            colorMap: xUi?.['color-map'] ?? undefined,
            colorRange: xUi?.['color-range'] ?? undefined,
            iconAge: xUi?.['icon-age'] ?? undefined,
            iconMap: xUi?.['icon-map'] ?? undefined,
            iconRange: xUi?.['icon-range'] ?? undefined,
          },
          value: formatFieldValue(raw, def),
        })
      }
    }
    return fields.sort((a, b) => a.label.localeCompare(b.label))
  }, [projectSchema, project])

  return (
    <>
      {attributeFields.map((field) => (
        <ProjectAttributeRow
          field={field}
          key={field.key}
          patch={patch}
          pending={pendingPath === `/${field.key}`}
        />
      ))}
    </>
  )
}
