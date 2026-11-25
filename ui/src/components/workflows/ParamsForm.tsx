import { useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Plus, X } from 'lucide-react'

import { listOrganizationMembers, listTeams } from '@/api/endpoints'
import { Checkbox } from '@/components/ui/checkbox'
import { Combobox, type ComboboxOption } from '@/components/ui/combobox'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { OrganizationMember } from '@/types'

import type { Condition } from './conditions'
import { ConditionsField } from './ConditionsField'
import { InputsField, MAX_INPUTS } from './InputsField'
import { ManualInputsField } from './ManualInputsField'
import type { OutputField } from './outputFields'
import { OutputFieldsField } from './OutputFieldsField'
import { TemplateInput } from './ReferencePicker'
import type { ReferenceGroup } from './references'
import type { ManualInput } from './runs'
import {
  type FieldSource,
  hasTemplate,
  isIdOrReference,
  isRecord,
  type ParamField,
  TRIGGER_PROJECT,
} from './schemaFields'
import { useSourceOptions, useStepChoices } from './workflowQueries'

interface ParamsFormProps {
  fields: ParamField[]
  idPrefix: string
  onChange: (name: string, value: unknown) => void
  /** Removes item `index` of a list field (branches also drop their edges). */
  onRemoveItem: (name: string, index: number) => void
  orgSlug: string
  params: Record<string, unknown>
  references: ReferenceGroup[]
  /** The workflow has a webhook trigger, so a run can have a project. */
  webhookProject: boolean
}

/** An email recipient: a team or a user, by graph node id. */
interface Recipient {
  id: string
  kind: 'team' | 'user'
}

/** A recipient in the form, with a key that stays with it on removal. */
interface RecipientRow extends Recipient {
  key: string
  referencing: boolean
}

/** The inspector form for a node's `params`, built from its type's schema. */
export function ParamsForm({
  fields,
  idPrefix,
  onChange,
  onRemoveItem,
  orgSlug,
  params,
  references,
  webhookProject,
}: ParamsFormProps) {
  return (
    <>
      {fields.map((field) => {
        const id = `${idPrefix}-${field.name}`
        const value = params[field.name]
        return (
          <FormField
            description={field.description}
            htmlFor={id}
            key={field.name}
            label={field.label}
            required={field.required}
          >
            <FieldControl
              field={field}
              id={id}
              onChange={(v) => onChange(field.name, v)}
              onRemoveItem={(i) => onRemoveItem(field.name, i)}
              orgSlug={orgSlug}
              params={params}
              references={references}
              value={value}
              webhookProject={webhookProject}
            />
          </FormField>
        )
      })}
    </>
  )
}

export function SelectField({
  id,
  label,
  onChange,
  options,
  value,
}: {
  id: string
  label?: string
  onChange: (value: string) => void
  options: { label: string; value: string }[]
  value: string
}) {
  return (
    <Select onValueChange={onChange} value={value}>
      <SelectTrigger aria-label={label} id={id}>
        <SelectValue placeholder="Choose…" />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

/** A list of enum values, as one checkbox per option. */
function ChecksField({
  id,
  label,
  onChange,
  options,
  value,
}: {
  id: string
  label: string
  onChange: (value: string[]) => void
  options: { label: string; value: string }[]
  value: string[]
}) {
  return (
    <div
      aria-label={label}
      className="flex flex-col gap-1.5"
      id={id}
      role="group"
    >
      {options.map((o) => (
        <label className="flex items-center gap-2 text-sm" key={o.value}>
          <Checkbox
            checked={value.includes(o.value)}
            onCheckedChange={(checked) =>
              onChange(
                checked
                  ? [...value, o.value]
                  : value.filter((v) => v !== o.value),
              )
            }
          />
          {o.label}
        </label>
      ))}
    </div>
  )
}

/**
 * A plugin step field with choices from its integration (ADR 0032). It
 * also takes free text, because the value can be a template.
 */
function ChoicesField({
  field,
  id,
  onChange,
  orgSlug,
  params,
  value,
}: {
  field: Extract<ParamField, { kind: 'choices' }>
  id: string
  onChange: (value: unknown) => void
  orgSlug: string
  params: Record<string, unknown>
  value: unknown
}) {
  const choices = useStepChoices(
    orgSlug,
    params.integration,
    field.step,
    field.name,
    Object.fromEntries(field.dependsOn.map((name) => [name, params[name]])),
  )
  const options = choices.data ?? []
  const placeholder = choices.isFetching ? 'Loading…' : 'Choose or type…'
  const error = choices.isError && (
    <p className="text-danger mt-1 text-xs">
      Could not load the choices. Type a value.
    </p>
  )
  if (!field.multiple) {
    return (
      <>
        <Combobox
          creatable
          id={id}
          // The "None" option clears an optional field.
          onChange={(v) => onChange(v || undefined)}
          options={
            field.required
              ? options
              : [{ label: 'None', value: '' }, ...options]
          }
          placeholder={placeholder}
          value={typeof value === 'string' ? value : ''}
        />
        {error}
      </>
    )
  }
  const selected = Array.isArray(value) ? value.map(String) : []
  const label = (v: string) => options.find((o) => o.value === v)?.label ?? v
  return (
    <div className="flex flex-col gap-1.5">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {selected.map((v) => (
            <span
              className="bg-secondary inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs"
              key={v}
            >
              {label(v)}
              <button
                aria-label={`Remove ${label(v)}`}
                className="text-secondary hover:text-primary"
                onClick={() => onChange(selected.filter((s) => s !== v))}
                type="button"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <Combobox
        creatable
        id={id}
        onChange={(v) => {
          if (v && !selected.includes(v)) onChange([...selected, v])
        }}
        options={options.filter((o) => !selected.includes(o.value))}
        placeholder={placeholder}
        value=""
      />
      {error}
    </div>
  )
}

function FieldControl({
  field,
  id,
  onChange,
  onRemoveItem,
  orgSlug,
  params,
  references,
  value,
  webhookProject,
}: {
  field: ParamField
  id: string
  onChange: (value: unknown) => void
  onRemoveItem: (index: number) => void
  orgSlug: string
  params: Record<string, unknown>
  references: ReferenceGroup[]
  value: unknown
  webhookProject: boolean
}) {
  switch (field.kind) {
    case 'boolean':
      return (
        <Switch
          checked={value === true}
          id={id}
          onCheckedChange={(checked) => onChange(checked)}
        />
      )
    case 'checks':
      return (
        <ChecksField
          id={id}
          label={field.label}
          onChange={onChange}
          options={field.options}
          value={Array.isArray(value) ? value.map(String) : []}
        />
      )
    case 'choices':
      return (
        <ChoicesField
          field={field}
          id={id}
          onChange={onChange}
          orgSlug={orgSlug}
          params={params}
          value={value}
        />
      )
    case 'code':
      return (
        <Textarea
          className="font-mono text-xs"
          id={id}
          onChange={(e) => onChange(e.target.value)}
          rows={10}
          spellCheck={false}
          value={typeof value === 'string' ? value : ''}
        />
      )
    case 'conditions':
      return (
        <ConditionsField
          id={id}
          key={id}
          label={field.label}
          onChange={onChange}
          operators={field.options}
          references={references}
          value={Array.isArray(value) ? (value as Condition[]) : []}
        />
      )
    case 'inputs':
      return (
        <InputsField
          id={id}
          key={id}
          label={field.label}
          // Only a script's inputs have a limit; a map such as the custom
          // fields of an agent step has none.
          limit={field.name === 'inputs' ? MAX_INPUTS : Infinity}
          onChange={onChange}
          references={references}
          value={isRecord(value) ? value : {}}
        />
      )
    case 'json':
      return <JsonField id={id} onChange={onChange} value={value} />
    case 'list':
      return (
        <ListField
          id={id}
          onChange={onChange}
          onRemove={onRemoveItem}
          value={Array.isArray(value) ? value.map(String) : []}
        />
      )
    case 'manualInputs':
      return (
        <ManualInputsField
          id={id}
          label={field.label}
          onChange={onChange}
          types={field.options}
          value={Array.isArray(value) ? (value as ManualInput[]) : []}
        />
      )
    case 'multiline':
      return (
        <TemplateInput
          className={cn(field.mono && 'font-mono text-xs')}
          groups={references}
          id={id}
          multiline
          onChange={onChange}
          value={typeof value === 'string' ? value : ''}
        />
      )
    case 'number':
      return (
        <Input
          id={id}
          onChange={(e) =>
            onChange(e.target.value === '' ? undefined : Number(e.target.value))
          }
          type="number"
          value={typeof value === 'number' ? value : ''}
        />
      )
    case 'outputFields':
      return (
        <OutputFieldsField
          id={id}
          label={field.label}
          onChange={onChange}
          value={Array.isArray(value) ? (value as OutputField[]) : []}
        />
      )
    case 'recipients':
      return (
        <RecipientsField
          id={id}
          onChange={onChange}
          orgSlug={orgSlug}
          references={references}
          value={Array.isArray(value) ? (value as Recipient[]) : []}
        />
      )
    case 'select':
      return (
        <SelectField
          id={id}
          onChange={onChange}
          options={field.options}
          value={typeof value === 'string' ? value : ''}
        />
      )
    case 'source':
      return (
        <SourceField
          id={id}
          onChange={onChange}
          optional={!field.required}
          orgSlug={orgSlug}
          plugin={field.plugin}
          source={field.source}
          value={typeof value === 'string' ? value : ''}
          webhookProject={webhookProject}
        />
      )
    case 'text':
      return (
        <TemplateInput
          groups={references}
          id={id}
          multiline={false}
          onChange={onChange}
          value={typeof value === 'string' ? value : ''}
        />
      )
  }
}

/** Any value the form has no control for, edited as JSON. */
function JsonField({
  id,
  onChange,
  value,
}: {
  id: string
  onChange: (value: unknown) => void
  value: unknown
}) {
  const [text, setText] = useState(() =>
    value === undefined ? '' : JSON.stringify(value, null, 2),
  )
  const [invalid, setInvalid] = useState(false)
  return (
    <>
      <Textarea
        aria-invalid={invalid}
        className="font-mono text-xs"
        id={id}
        onChange={(e) => {
          setText(e.target.value)
          if (e.target.value.trim() === '') {
            setInvalid(false)
            onChange(undefined)
            return
          }
          try {
            onChange(JSON.parse(e.target.value))
            setInvalid(false)
          } catch {
            setInvalid(true)
          }
        }}
        rows={4}
        value={text}
      />
      {invalid && <p className="text-danger mt-1 text-xs">Not valid JSON.</p>}
    </>
  )
}

function ListField({
  id,
  onChange,
  onRemove,
  value,
}: {
  id: string
  onChange: (value: string[]) => void
  onRemove: (index: number) => void
  value: string[]
}) {
  return (
    <div className="flex flex-col gap-2" id={id}>
      {value.map((item, i) => (
        <div className="flex items-center gap-1.5" key={i}>
          <span className="text-tertiary w-5.5 text-center font-mono text-xs">
            {i + 1}
          </span>
          <Input
            aria-label={`Item ${i + 1}`}
            className="h-8.5"
            onChange={(e) =>
              onChange(value.map((v, j) => (j === i ? e.target.value : v)))
            }
            value={item}
          />
          <button
            aria-label={`Remove item ${i + 1}`}
            className="text-secondary hover:bg-secondary flex size-7 shrink-0 items-center justify-center rounded-md"
            onClick={() => onRemove(i)}
            type="button"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
      <button
        className="border-input text-secondary hover:border-amber-border hover:text-primary flex h-8.5 items-center justify-center gap-1.5 rounded-md border border-dashed text-sm"
        onClick={() => onChange([...value, `Option ${value.length + 1}`])}
        type="button"
      >
        <Plus className="size-3.5" />
        Add
      </button>
    </div>
  )
}

/**
 * Email recipients: teams and users by graph node id, picked from the
 * organization's teams and active members. A user recipient can also be
 * a reference, such as a user that an earlier step returns.
 */
function RecipientsField({
  id,
  onChange,
  orgSlug,
  references,
  value,
}: {
  id: string
  onChange: (value: Recipient[]) => void
  orgSlug: string
  references: ReferenceGroup[]
  value: Recipient[]
}) {
  const teams = useQuery({
    queryFn: ({ signal }) => listTeams(orgSlug, signal),
    queryKey: queryKeys.teams(orgSlug),
    // A Select item cannot take an empty value, so skip a team with no id.
    select: (rows) =>
      rows.flatMap((t) => (t.id ? [{ label: t.name, value: t.id }] : [])),
  })
  const [rows, setRows] = useState(() => value.map(recipientRow))
  const update = (next: RecipientRow[]) => {
    setRows(next)
    onChange(next.map((row) => ({ id: row.id, kind: row.kind })))
  }
  const set = (index: number, patch: Partial<RecipientRow>) =>
    update(rows.map((row, i) => (i === index ? { ...row, ...patch } : row)))
  return (
    <div className="flex flex-col gap-2" id={id}>
      {rows.map((row, i) => (
        <div className="flex items-center gap-1.5" key={row.key}>
          <div className="w-24 shrink-0">
            <SelectField
              id={`${id}-${i}-kind`}
              onChange={(kind) =>
                set(i, {
                  id: '',
                  kind: kind as Recipient['kind'],
                  referencing: false,
                })
              }
              options={[
                { label: 'Team', value: 'team' },
                { label: 'User', value: 'user' },
              ]}
              value={row.kind}
            />
          </div>
          <div className="min-w-0 flex-1">
            {row.kind === 'team' ? (
              <SelectField
                id={`${id}-${i}-id`}
                onChange={(teamId) => set(i, { id: teamId })}
                options={teams.data ?? []}
                value={row.id}
              />
            ) : (
              <UserRecipientField
                id={`${id}-${i}-id`}
                onChange={(patch) => set(i, patch)}
                orgSlug={orgSlug}
                references={references}
                referencing={row.referencing}
                value={row.id}
              />
            )}
          </div>
          <button
            aria-label={`Remove recipient ${i + 1}`}
            className="text-secondary hover:bg-secondary flex size-7 shrink-0 items-center justify-center rounded-md"
            onClick={() => update(rows.filter((_, j) => j !== i))}
            type="button"
          >
            <X className="size-3.5" />
          </button>
        </div>
      ))}
      <button
        className="border-input text-secondary hover:border-amber-border hover:text-primary flex h-8.5 items-center justify-center gap-1.5 rounded-md border border-dashed text-sm"
        onClick={() =>
          update([...rows, recipientRow({ id: '', kind: 'team' })])
        }
        type="button"
      >
        <Plus className="size-3.5" />
        Add recipient
      </button>
    </div>
  )
}

function SourceField({
  id,
  onChange,
  optional,
  orgSlug,
  plugin,
  source,
  value,
  webhookProject,
}: {
  id: string
  onChange: (value: string | undefined) => void
  optional: boolean
  orgSlug: string
  plugin?: string
  source: FieldSource
  value: string
  webhookProject: boolean
}) {
  const { loading, options } = useSourceOptions(orgSlug, source, plugin)
  const detect = source === 'project' && webhookProject
  return (
    <>
      <Combobox
        id={id}
        // The "None" option clears an optional field.
        onChange={(v) => onChange(v || undefined)}
        options={[
          ...(optional ? [{ label: 'None', value: '' }] : []),
          ...(detect
            ? [{ label: 'Detected from webhook', value: TRIGGER_PROJECT }]
            : []),
          ...options,
        ]}
        placeholder={loading ? 'Loading…' : 'Choose…'}
        value={value}
      />
      {detect && value === TRIGGER_PROJECT && (
        <p className="text-secondary mt-1 text-xs">
          The project that the webhook matched. A delivery that matches more
          than one project starts one run for each.
        </p>
      )}
    </>
  )
}

const USE_REFERENCE = '__reference__'

function memberOptions(members: OrganizationMember[]): ComboboxOption[] {
  return members
    .filter((member) => member.is_active)
    .map((member) => ({
      label: member.display_name
        ? `${member.display_name} <${member.email}>`
        : member.email,
      value: member.id,
    }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

function recipientRow(recipient: Recipient): RecipientRow {
  return {
    ...recipient,
    key: crypto.randomUUID(),
    referencing: recipient.kind === 'user' && hasTemplate(recipient.id),
  }
}

function UserRecipientField({
  id,
  onChange,
  orgSlug,
  references,
  referencing,
  value,
}: {
  id: string
  onChange: (patch: { id: string; referencing?: boolean }) => void
  orgSlug: string
  references: ReferenceGroup[]
  referencing: boolean
  value: string
}) {
  const members = useQuery({
    queryFn: ({ signal }) => listOrganizationMembers(orgSlug, signal),
    queryKey: queryKeys.organizationMembers(orgSlug),
    select: memberOptions,
  })
  if (referencing) {
    return (
      <>
        <TemplateInput
          className="font-mono text-xs"
          groups={references}
          id={id}
          multiline={false}
          onChange={(next) => onChange({ id: next })}
          value={value}
        />
        {!isIdOrReference(value) && (
          <p className="text-danger mt-1 text-xs">
            Use a user id or one reference such as {'{{ trigger.user }}'}.
          </p>
        )}
        <button
          className="text-secondary hover:text-primary mt-1 text-xs"
          onClick={() => onChange({ id: '', referencing: false })}
          type="button"
        >
          Pick a user
        </button>
      </>
    )
  }
  const options = members.data ?? []
  const known =
    !value || members.isPending || options.some((o) => o.value === value)
  return (
    <Combobox
      id={id}
      onChange={(next) =>
        onChange(
          next === USE_REFERENCE ? { id: '', referencing: true } : { id: next },
        )
      }
      options={[
        ...options,
        ...(known ? [] : [{ label: value, value }]),
        { label: 'Use a reference…', value: USE_REFERENCE },
      ]}
      placeholder={members.isPending ? 'Loading…' : 'Choose a user…'}
      value={value}
    />
  )
}
