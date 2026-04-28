import { Filter } from 'lucide-react'

import { Checkbox } from '@/components/ui/checkbox'
import type { Environment, ProjectType } from '@/types'

interface BlueprintFilterEditorProps {
  availableEnvironments: Environment[]
  availableProjectTypes: ProjectType[]
  envIsError: boolean
  envLoading: boolean
  filterEnabled: boolean
  isLoading: boolean
  ptIsError: boolean
  ptLoading: boolean
  selectedEnvironments: Set<string>
  selectedProjectTypes: Set<string>
  setFilterEnabled: (value: boolean) => void
  setSelectedEnvironments: (value: Set<string>) => void
  setSelectedProjectTypes: (value: Set<string>) => void
}

export function BlueprintFilterEditor({
  availableEnvironments,
  availableProjectTypes,
  envIsError,
  envLoading,
  filterEnabled,
  isLoading,
  ptIsError,
  ptLoading,
  selectedEnvironments,
  selectedProjectTypes,
  setFilterEnabled,
  setSelectedEnvironments,
  setSelectedProjectTypes,
}: BlueprintFilterEditorProps) {
  return (
    <div className="rounded-lg border border-border bg-card p-6">
      <div className="mb-4 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Filter className="h-4 w-4 text-tertiary" />
          <h3 className="text-sm font-medium text-primary">
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
              }
            }}
          />
          <label
            className="cursor-pointer select-none text-sm text-secondary"
            htmlFor="filter-enabled"
          >
            Enable filter
          </label>
        </div>
      </div>

      {filterEnabled ? (
        <div className="space-y-5">
          <p className="text-xs text-tertiary">
            Select which project types and environments this blueprint applies
            to. Leave a section unchecked to apply to all.
          </p>

          {/* Project Type filter */}
          <div>
            <label className="mb-2 block text-sm font-medium text-secondary">
              Project Types
            </label>
            {ptLoading ? (
              <p className="text-xs italic text-tertiary">
                Loading project types...
              </p>
            ) : ptIsError ? (
              <p className="text-xs italic text-danger">
                Failed to load project types
              </p>
            ) : availableProjectTypes.length === 0 ? (
              <p className="text-xs italic text-tertiary">
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
                    <label
                      className={
                        'cursor-pointer select-none text-sm text-secondary'
                      }
                      htmlFor={`filter-pt-${pt.slug}`}
                    >
                      {pt.name}
                    </label>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* Environment filter */}
          <div>
            <label className="mb-2 block text-sm font-medium text-secondary">
              Environments
            </label>
            {envLoading ? (
              <p className="text-xs italic text-tertiary">
                Loading environments...
              </p>
            ) : envIsError ? (
              <p className="text-xs italic text-danger">
                Failed to load environments
              </p>
            ) : availableEnvironments.length === 0 ? (
              <p className="text-xs italic text-tertiary">
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
                    <label
                      className={
                        'cursor-pointer select-none text-sm text-secondary'
                      }
                      htmlFor={`filter-env-${env.slug}`}
                    >
                      {env.name}
                    </label>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      ) : (
        <p className="text-sm text-tertiary">
          No filter configured. This blueprint will apply to all entities of its
          type.
        </p>
      )}
    </div>
  )
}
