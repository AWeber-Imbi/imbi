import { memo, useCallback, useMemo } from 'react'

import type {
  ProjectSchemaResponse,
  ProjectSchemaSectionProperty,
} from '@/api/endpoints'
import { AttributeValue } from '@/components/ui/attribute-value'
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from '@/components/ui/hover-card'
import { isFieldEditable } from '@/components/ui/inline-edit/field-policy'
import { InlineField } from '@/components/ui/inline-edit/InlineField'
import {
  formatFieldKey,
  formatFieldValue,
  resolveFieldValue,
} from '@/lib/project-field-formatting'
import type { Project } from '@/types'

interface AttributeField {
  def: ProjectSchemaSectionProperty
  description?: string
  key: string
  label: string
  rawValue: unknown
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
    value: fieldValue,
  } = field

  const handleCommit = useCallback(
    (v: unknown) => patch(`/${key}`, v),
    [patch, key],
  )

  const editable = isFieldEditable(key, def)
  const richDisplay =
    fieldValue !== null ? (
      <AttributeValue def={def} rawValue={rawValue} />
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
  // fallow-ignore-next-line complexity
  const attributeFields = useMemo<AttributeField[]>(() => {
    if (!projectSchema) return []
    const seen = new Set<string>()
    const fields: AttributeField[] = []
    for (const section of projectSchema.sections) {
      // Environment-scoped (relationship-blueprint) attributes are rendered
      // per-environment in the Environments card, not as project attributes.
      if (section.scope === 'environment') continue
      for (const [key, def] of Object.entries(section.properties)) {
        if (seen.has(key) || key === 'url') continue
        seen.add(key)
        const raw = resolveFieldValue(key, section, project)
        fields.push({
          def,
          description: def.description ?? undefined,
          key,
          label: def.title || formatFieldKey(key),
          rawValue: raw,
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
