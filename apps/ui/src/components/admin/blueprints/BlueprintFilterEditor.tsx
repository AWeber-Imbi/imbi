import { Filter } from 'lucide-react'
import { Checkbox } from '@/components/ui/checkbox'
import type { Environment, ProjectType } from '@/types'

interface BlueprintFilterEditorProps {
  filterEnabled: boolean
  setFilterEnabled: (value: boolean) => void
  selectedProjectTypes: Set<string>
  setSelectedProjectTypes: (value: Set<string>) => void
  selectedEnvironments: Set<string>
  setSelectedEnvironments: (value: Set<string>) => void
  availableProjectTypes: ProjectType[]
  ptLoading: boolean
  ptIsError: boolean
  availableEnvironments: Environment[]
  envLoading: boolean
  envIsError: boolean
  isLoading: boolean
}

export function BlueprintFilterEditor({
  filterEnabled,
  setFilterEnabled,
  selectedProjectTypes,
  setSelectedProjectTypes,
  selectedEnvironments,
  setSelectedEnvironments,
  availableProjectTypes,
  ptLoading,
  ptIsError,
  availableEnvironments,
  envLoading,
  envIsError,
  isLoading,
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
            id="filter-enabled"
            checked={filterEnabled}
            onCheckedChange={(checked) => {
              setFilterEnabled(checked === true)
              if (!checked) {
                setSelectedProjectTypes(new Set())
                setSelectedEnvironments(new Set())
              }
            }}
            disabled={isLoading}
          />
          <label
            htmlFor="filter-enabled"
            className="cursor-pointer select-none text-sm text-secondary"
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
                  <div key={pt.slug} className="flex items-center gap-2">
                    <Checkbox
                      id={`filter-pt-${pt.slug}`}
                      checked={selectedProjectTypes.has(pt.slug)}
                      onCheckedChange={(checked) => {
                        const next = new Set(selectedProjectTypes)
                        if (checked) {
                          next.add(pt.slug)
                        } else {
                          next.delete(pt.slug)
                        }
                        setSelectedProjectTypes(next)
                      }}
                      disabled={isLoading}
                    />
                    <label
                      htmlFor={`filter-pt-${pt.slug}`}
                      className={
                        'cursor-pointer select-none text-sm text-secondary'
                      }
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
                  <div key={env.slug} className="flex items-center gap-2">
                    <Checkbox
                      id={`filter-env-${env.slug}`}
                      checked={selectedEnvironments.has(env.slug)}
                      onCheckedChange={(checked) => {
                        const next = new Set(selectedEnvironments)
                        if (checked) {
                          next.add(env.slug)
                        } else {
                          next.delete(env.slug)
                        }
                        setSelectedEnvironments(next)
                      }}
                      disabled={isLoading}
                    />
                    <label
                      htmlFor={`filter-env-${env.slug}`}
                      className={
                        'cursor-pointer select-none text-sm text-secondary'
                      }
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
