import { Filter } from 'lucide-react'

import { PRIORITIES, priorityLabel } from '@/components/agents/priority'
import { LabelInput, TICKET_TYPES } from '@/components/agents/ticketAttributes'
import { Checkbox } from '@/components/ui/checkbox'
import { Label } from '@/components/ui/label'
import type { Environment, ProjectType } from '@/types'

interface BlueprintFilterEditorProps {
  availableEnvironments: Environment[]
  availableProjectTypes: ProjectType[]
  envIsError: boolean
  envLoading: boolean
  filterEnabled: boolean
  isLoading: boolean
  /** A Ticket blueprint filters on ticket fields, not project fields. */
  isTicket: boolean
  labels: string[]
  orgSlug: string
  ptIsError: boolean
  ptLoading: boolean
  selectedEnvironments: Set<string>
  selectedPriorities: Set<string>
  selectedProjectTypes: Set<string>
  selectedTicketTypes: Set<string>
  setFilterEnabled: (value: boolean) => void
  setLabels: (value: string[]) => void
  setSelectedEnvironments: (value: Set<string>) => void
  setSelectedPriorities: (value: Set<string>) => void
  setSelectedProjectTypes: (value: Set<string>) => void
  setSelectedTicketTypes: (value: Set<string>) => void
}

const PRIORITY_OPTIONS = PRIORITIES.map((p) => ({
  label: priorityLabel(p),
  value: p,
}))

export function BlueprintFilterEditor({
  availableEnvironments,
  availableProjectTypes,
  envIsError,
  envLoading,
  filterEnabled,
  isLoading,
  isTicket,
  labels,
  orgSlug,
  ptIsError,
  ptLoading,
  selectedEnvironments,
  selectedPriorities,
  selectedProjectTypes,
  selectedTicketTypes,
  setFilterEnabled,
  setLabels,
  setSelectedEnvironments,
  setSelectedPriorities,
  setSelectedProjectTypes,
  setSelectedTicketTypes,
}: BlueprintFilterEditorProps) {
  return (
    <div className="border-border bg-card rounded-lg border p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Filter className="text-tertiary size-4" />
          <h3 className="text-primary text-sm font-medium">
            Conditional Filter
          </h3>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            checked={filterEnabled}
            disabled={isLoading}
            id="filter-enabled"
            onCheckedChange={(checked) => {
              setFilterEnabled(checked === true)
              if (!checked) {
                setSelectedProjectTypes(new Set())
                setSelectedEnvironments(new Set())
                setSelectedTicketTypes(new Set())
                setSelectedPriorities(new Set())
                setLabels([])
              }
            }}
          />
          <Label
            className="text-secondary cursor-pointer text-sm select-none"
            htmlFor="filter-enabled"
          >
            Enable filter
          </Label>
        </div>
      </div>

      {filterEnabled && isTicket ? (
        <div className="space-y-5">
          <p className="text-tertiary text-xs">
            Select which tickets this blueprint applies to. Leave a section
            empty to apply to all. A ticket matches the labels when it has one
            or more of them.
          </p>
          <CheckboxGroup
            disabled={isLoading}
            idPrefix="filter-tt"
            label="Ticket Types"
            onChange={setSelectedTicketTypes}
            options={TICKET_TYPES}
            selected={selectedTicketTypes}
          />
          <CheckboxGroup
            disabled={isLoading}
            idPrefix="filter-priority"
            label="Priorities"
            onChange={setSelectedPriorities}
            options={PRIORITY_OPTIONS}
            selected={selectedPriorities}
          />
          <div>
            <Label
              className="text-secondary mb-2 block text-sm font-medium"
              htmlFor="filter-labels"
            >
              Labels
            </Label>
            <LabelInput
              disabled={isLoading}
              id="filter-labels"
              onChange={setLabels}
              orgSlug={orgSlug}
              value={labels}
            />
          </div>
        </div>
      ) : filterEnabled ? (
        <div className="space-y-5">
          <p className="text-tertiary text-xs">
            Select which project types and environments this blueprint applies
            to. Leave a section unchecked to apply to all.
          </p>

          {/* Project Type filter */}
          <div>
            <Label className="text-secondary mb-2 block text-sm font-medium">
              Project Types
            </Label>
            {ptLoading ? (
              <p className="text-tertiary text-xs italic">
                Loading project types...
              </p>
            ) : ptIsError ? (
              <p className="text-danger text-xs italic">
                Failed to load project types
              </p>
            ) : availableProjectTypes.length === 0 ? (
              <p className="text-tertiary text-xs italic">
                No project types available
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                {availableProjectTypes.map((pt) => (
                  <div className="flex items-center gap-2" key={pt.slug}>
                    <Checkbox
                      checked={selectedProjectTypes.has(pt.slug)}
                      disabled={isLoading}
                      id={`filter-pt-${pt.slug}`}
                      onCheckedChange={(checked) => {
                        const next = new Set(selectedProjectTypes)
                        if (checked) {
                          next.add(pt.slug)
                        } else {
                          next.delete(pt.slug)
                        }
                        setSelectedProjectTypes(next)
                      }}
                    />
                    <Label
                      className={
                        'text-secondary cursor-pointer text-sm select-none'
                      }
                      htmlFor={`filter-pt-${pt.slug}`}
                    >
                      {pt.name}
                    </Label>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Environment filter */}
          <div>
            <Label className="text-secondary mb-2 block text-sm font-medium">
              Environments
            </Label>
            {envLoading ? (
              <p className="text-tertiary text-xs italic">
                Loading environments...
              </p>
            ) : envIsError ? (
              <p className="text-danger text-xs italic">
                Failed to load environments
              </p>
            ) : availableEnvironments.length === 0 ? (
              <p className="text-tertiary text-xs italic">
                No environments available
              </p>
            ) : (
              <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
                {availableEnvironments.map((env) => (
                  <div className="flex items-center gap-2" key={env.slug}>
                    <Checkbox
                      checked={selectedEnvironments.has(env.slug)}
                      disabled={isLoading}
                      id={`filter-env-${env.slug}`}
                      onCheckedChange={(checked) => {
                        const next = new Set(selectedEnvironments)
                        if (checked) {
                          next.add(env.slug)
                        } else {
                          next.delete(env.slug)
                        }
                        setSelectedEnvironments(next)
                      }}
                    />
                    <Label
                      className={
                        'text-secondary cursor-pointer text-sm select-none'
                      }
                      htmlFor={`filter-env-${env.slug}`}
                    >
                      {env.name}
                    </Label>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <p className="text-tertiary text-sm">
          No filter configured. This blueprint will apply to all entities of its
          type.
        </p>
      )}
    </div>
  )
}

/** A labeled grid of checkboxes, one for each option. */
function CheckboxGroup({
  disabled,
  idPrefix,
  label,
  onChange,
  options,
  selected,
}: {
  disabled: boolean
  idPrefix: string
  label: string
  onChange: (value: Set<string>) => void
  options: { label: string; value: string }[]
  selected: Set<string>
}) {
  return (
    <div>
      <Label className="text-secondary mb-2 block text-sm font-medium">
        {label}
      </Label>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-4">
        {options.map((o) => (
          <div className="flex items-center gap-2" key={o.value}>
            <Checkbox
              checked={selected.has(o.value)}
              disabled={disabled}
              id={`${idPrefix}-${o.value}`}
              onCheckedChange={(checked) => {
                const next = new Set(selected)
                if (checked) {
                  next.add(o.value)
                } else {
                  next.delete(o.value)
                }
                onChange(next)
              }}
            />
            <Label
              className="text-secondary cursor-pointer text-sm select-none"
              htmlFor={`${idPrefix}-${o.value}`}
            >
              {o.label}
            </Label>
          </div>
        ))}
      </div>
    </div>
  )
}
