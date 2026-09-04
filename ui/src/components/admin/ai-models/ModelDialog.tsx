import { useState } from 'react'

import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorBanner } from '@/components/ui/error-banner'
import { FormField } from '@/components/ui/form-field'
import { Input } from '@/components/ui/input'
import {
  SegmentedControl,
  SegmentedControlItem,
} from '@/components/ui/segmented-control'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { cn } from '@/lib/utils'
import type {
  AIModel,
  AIModelAccessScope,
  AIModelKind,
  AIProvider,
  Team,
} from '@/types'

import { decimalToNumber } from './decimal'

export interface ModelFormValues {
  access_scope: AIModelAccessScope
  allowed_team_ids: string[]
  context_window: null | number
  default_temperature: null | number
  default_top_p: null | number
  enabled: boolean
  input_cost_per_million: null | number
  kind: AIModelKind
  max_output_tokens: null | number
  model_id: string
  monthly_spend_cap: null | number
  name: string
  output_cost_per_million: null | number
  provider_id: string
}

interface ModelDialogProps {
  defaultProviderId?: string
  error?: unknown
  isPending: boolean
  model: AIModel | null
  onClose: () => void
  onDelete?: (model: AIModel) => void
  onSubmit: (values: ModelFormValues) => void
  open: boolean
  providers: AIProvider[]
  teams: Team[]
}

/** The fields typed as free text but submitted as numbers. */
type NumericKey =
  | 'context_window'
  | 'default_temperature'
  | 'default_top_p'
  | 'input_cost_per_million'
  | 'max_output_tokens'
  | 'monthly_spend_cap'
  | 'output_cost_per_million'

// Advisory until spend enforcement ships — see the plan's decision 8.
const CAP_HELP =
  'Advisory until spend enforcement ships; Imbi does not yet block calls at the cap.'

const NUMERIC_KEYS: NumericKey[] = [
  'context_window',
  'default_temperature',
  'default_top_p',
  'input_cost_per_million',
  'max_output_tokens',
  'monthly_spend_cap',
  'output_cost_per_million',
]

export function ModelDialog({
  defaultProviderId,
  error,
  isPending,
  model,
  onClose,
  onDelete,
  onSubmit,
  open,
  providers,
  teams,
}: ModelDialogProps) {
  const [step, setStep] = useState<1 | 2>(1)
  const [values, setValues] = useState<ModelFormValues>(() =>
    initialValues(model, defaultProviderId),
  )
  // Numeric inputs keep what was typed so a half-finished or invalid
  // entry surfaces an error instead of silently clearing to null.
  const [text, setText] = useState<Record<NumericKey, string>>(() =>
    initialText(model, defaultProviderId),
  )
  const [confirmingDelete, setConfirmingDelete] = useState(false)

  const set = <K extends keyof ModelFormValues>(
    key: K,
    value: ModelFormValues[K],
  ) => setValues((current) => ({ ...current, [key]: value }))

  const setNumeric = (key: NumericKey, raw: string) => {
    setText((current) => ({ ...current, [key]: raw }))
    const trimmed = raw.trim()
    if (trimmed === '') {
      set(key, null)
      return
    }
    const parsed = Number(trimmed)
    if (!Number.isNaN(parsed)) set(key, parsed)
  }

  const numericError = (key: NumericKey): string | undefined => {
    const trimmed = text[key].trim()
    if (trimmed === '' || !Number.isNaN(Number(trimmed))) return undefined
    return 'Enter a number.'
  }
  const hasNumericErrors = NUMERIC_KEYS.some((key) => numericError(key))

  const canContinue = !!values.provider_id && values.model_id.trim().length > 0

  const toggleTeam = (teamId: string) => {
    const selected = values.allowed_team_ids.includes(teamId)
      ? values.allowed_team_ids.filter((id) => id !== teamId)
      : [...values.allowed_team_ids, teamId]
    setValues((current) => ({
      ...current,
      access_scope: selected.length === 0 ? 'organization' : 'restricted',
      allowed_team_ids: selected,
    }))
  }

  const selectAllTeams = () =>
    setValues((current) => ({
      ...current,
      access_scope: 'organization',
      allowed_team_ids: [],
    }))

  const handleSubmit = () => {
    onSubmit({
      ...values,
      allowed_team_ids:
        values.access_scope === 'restricted' ? values.allowed_team_ids : [],
      name: values.name.trim() || values.model_id.trim(),
    })
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next) onClose()
      }}
      open={open}
    >
      <DialogContent className="max-w-150">
        <DialogHeader>
          <span className="text-tertiary text-xs tracking-wider uppercase">
            Step {step} of 2
          </span>
          <DialogTitle>{model ? 'Edit model' : 'Add model'}</DialogTitle>
          <DialogDescription>
            {step === 1
              ? 'Identify the model and the provider that serves it.'
              : 'Limits, cost and who inside the organization may use it.'}
          </DialogDescription>
        </DialogHeader>

        <div className="max-h-[60vh] space-y-4 overflow-y-auto p-6">
          {error != null && (
            <ErrorBanner error={error} title="Failed to save model" />
          )}
          {step === 1 ? (
            <>
              <FormField label="Provider" required>
                <Select
                  onValueChange={(v) => set('provider_id', v)}
                  value={values.provider_id}
                >
                  <SelectTrigger aria-label="Provider">
                    <SelectValue placeholder="Select a provider" />
                  </SelectTrigger>
                  <SelectContent>
                    {providers.map((provider) => (
                      <SelectItem key={provider.id} value={provider.id}>
                        {provider.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </FormField>
              <FormField
                description="The identifier Imbi sends to the provider. For self-hosted gateways, a full inference URL is accepted."
                htmlFor="ai-model-id"
                label="Model name or URL"
                required
              >
                <Input
                  className="font-mono"
                  id="ai-model-id"
                  onChange={(e) => set('model_id', e.target.value)}
                  value={values.model_id}
                />
              </FormField>
              <FormField htmlFor="ai-model-name" label="Display name">
                <Input
                  id="ai-model-name"
                  onChange={(e) => set('name', e.target.value)}
                  placeholder="What engineers see in the model picker"
                  value={values.name}
                />
              </FormField>
              <FormField label="Interface">
                <SegmentedControl
                  ariaLabel="Interface"
                  onValueChange={(v) => set('kind', v as AIModelKind)}
                  value={values.kind}
                >
                  <SegmentedControlItem value="chat">Chat</SegmentedControlItem>
                  <SegmentedControlItem value="completion">
                    Completion
                  </SegmentedControlItem>
                </SegmentedControl>
              </FormField>
            </>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-4">
                <NumberField
                  error={numericError('context_window')}
                  id="ai-model-ctx"
                  label="Context window"
                  onChange={(raw) => setNumeric('context_window', raw)}
                  value={text.context_window}
                />
                <NumberField
                  error={numericError('max_output_tokens')}
                  id="ai-model-max-out"
                  label="Max output tokens"
                  onChange={(raw) => setNumeric('max_output_tokens', raw)}
                  value={text.max_output_tokens}
                />
                <NumberField
                  error={numericError('input_cost_per_million')}
                  id="ai-model-cost-in"
                  label="Input cost / 1M tokens"
                  onChange={(raw) => setNumeric('input_cost_per_million', raw)}
                  value={text.input_cost_per_million}
                />
                <NumberField
                  error={numericError('output_cost_per_million')}
                  id="ai-model-cost-out"
                  label="Output cost / 1M tokens"
                  onChange={(raw) => setNumeric('output_cost_per_million', raw)}
                  value={text.output_cost_per_million}
                />
              </div>
              <div className="border-tertiary border-t" />
              <div className="grid grid-cols-2 gap-4">
                <NumberField
                  error={numericError('default_temperature')}
                  id="ai-model-temp"
                  label="Default temperature"
                  onChange={(raw) => setNumeric('default_temperature', raw)}
                  value={text.default_temperature}
                />
                <NumberField
                  error={numericError('default_top_p')}
                  id="ai-model-top-p"
                  label="Default top_p"
                  onChange={(raw) => setNumeric('default_top_p', raw)}
                  value={text.default_top_p}
                />
              </div>
              <NumberField
                description={CAP_HELP}
                error={numericError('monthly_spend_cap')}
                id="ai-model-cap"
                label="Monthly spend cap"
                onChange={(raw) => setNumeric('monthly_spend_cap', raw)}
                value={text.monthly_spend_cap}
              />
              <FormField
                description={
                  values.access_scope === 'organization'
                    ? 'Available to every team in the organization.'
                    : `${values.allowed_team_ids.length} team(s) selected.`
                }
                label="Allowed teams"
              >
                <div className="flex flex-wrap gap-1.5">
                  <TeamChip
                    active={values.access_scope === 'organization'}
                    label="All teams"
                    onClick={selectAllTeams}
                  />
                  {teams.map((team) =>
                    team.id ? (
                      <TeamChip
                        active={values.allowed_team_ids.includes(team.id)}
                        key={team.id}
                        label={team.name}
                        onClick={() => toggleTeam(team.id!)}
                      />
                    ) : null,
                  )}
                </div>
              </FormField>
              <div className="border-tertiary flex items-center justify-between rounded-md border p-3">
                <div>
                  <div className="text-primary text-sm font-medium">
                    Enable immediately
                  </div>
                  <p className="text-tertiary text-sm">
                    Makes the model selectable as soon as it is created.
                  </p>
                </div>
                <Switch
                  aria-label="Enable immediately"
                  checked={values.enabled}
                  onCheckedChange={(enabled) => set('enabled', enabled)}
                />
              </div>
            </>
          )}
        </div>

        <DialogFooter>
          {step === 2 && model && onDelete && (
            <button
              className="text-destructive mr-auto text-sm font-medium"
              onClick={() => setConfirmingDelete(true)}
              type="button"
            >
              Delete model
            </button>
          )}
          {step === 1 ? (
            <>
              <button
                className="text-secondary hover:text-primary text-sm font-medium"
                onClick={onClose}
                type="button"
              >
                Cancel
              </button>
              <button
                className={cn(
                  'rounded-md bg-action px-4 py-2 text-sm font-medium text-action-foreground hover:bg-action-hover',
                  !canContinue && 'pointer-events-none opacity-50',
                )}
                disabled={!canContinue}
                onClick={() => setStep(2)}
                type="button"
              >
                Continue
              </button>
            </>
          ) : (
            <>
              <button
                className="text-secondary hover:text-primary text-sm font-medium"
                onClick={() => setStep(1)}
                type="button"
              >
                Back
              </button>
              <button
                className="bg-action text-action-foreground hover:bg-action-hover rounded-md px-4 py-2 text-sm font-medium disabled:opacity-50"
                disabled={isPending || hasNumericErrors}
                onClick={handleSubmit}
                type="button"
              >
                {model ? 'Save changes' : 'Create model'}
              </button>
            </>
          )}
        </DialogFooter>
      </DialogContent>

      {model && onDelete && (
        <ConfirmDialog
          confirmLabel="Delete model"
          description="This cannot be undone. Anything referencing this model by slug stops resolving."
          onCancel={() => setConfirmingDelete(false)}
          onConfirm={() => {
            setConfirmingDelete(false)
            onDelete(model)
          }}
          open={confirmingDelete}
          title={`Delete ${model.name}?`}
        />
      )}
    </Dialog>
  )
}

function initialText(
  model: AIModel | null,
  _defaultProviderId?: string,
): Record<NumericKey, string> {
  const seed = initialValues(model, _defaultProviderId)
  const asText = (value: null | number) => (value === null ? '' : String(value))
  return {
    context_window: asText(seed.context_window),
    default_temperature: asText(seed.default_temperature),
    default_top_p: asText(seed.default_top_p),
    input_cost_per_million: asText(seed.input_cost_per_million),
    max_output_tokens: asText(seed.max_output_tokens),
    monthly_spend_cap: asText(seed.monthly_spend_cap),
    output_cost_per_million: asText(seed.output_cost_per_million),
  }
}

function initialValues(
  model: AIModel | null,
  defaultProviderId?: string,
): ModelFormValues {
  if (!model) {
    return {
      access_scope: 'organization',
      allowed_team_ids: [],
      context_window: null,
      default_temperature: null,
      default_top_p: null,
      enabled: true,
      input_cost_per_million: null,
      kind: 'chat',
      max_output_tokens: null,
      model_id: '',
      monthly_spend_cap: null,
      name: '',
      output_cost_per_million: null,
      provider_id: defaultProviderId ?? '',
    }
  }
  return {
    access_scope: model.access_scope,
    allowed_team_ids: model.allowed_teams.map((team) => team.id),
    context_window: model.context_window,
    default_temperature: model.default_temperature,
    default_top_p: model.default_top_p,
    enabled: model.enabled,
    input_cost_per_million: decimalToNumber(model.input_cost_per_million),
    kind: model.kind,
    max_output_tokens: model.max_output_tokens,
    model_id: model.model_id,
    monthly_spend_cap: decimalToNumber(model.monthly_spend_cap),
    name: model.name,
    output_cost_per_million: decimalToNumber(model.output_cost_per_million),
    provider_id: model.provider_id,
  }
}

function NumberField({
  description,
  error,
  id,
  label,
  onChange,
  value,
}: {
  description?: string
  error?: string
  id: string
  label: string
  onChange: (raw: string) => void
  value: string
}) {
  return (
    <FormField
      description={description}
      error={error}
      htmlFor={id}
      label={label}
      touched={!!error}
    >
      <Input
        id={id}
        inputMode="decimal"
        onChange={(e) => onChange(e.target.value)}
        value={value}
      />
    </FormField>
  )
}

function TeamChip({
  active,
  label,
  onClick,
}: {
  active: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      aria-pressed={active}
      className={cn(
        'rounded-sm border px-2 py-0.5 text-xs font-medium',
        active
          ? 'border-transparent bg-amber-bg text-amber-text'
          : 'border-secondary text-secondary',
      )}
      onClick={onClick}
      type="button"
    >
      {label}
    </button>
  )
}
