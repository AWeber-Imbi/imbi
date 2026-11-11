import { useMemo, useState } from 'react'

import { useQuery } from '@tanstack/react-query'
import { Check, ChevronDown, ChevronUp } from 'lucide-react'

import { listAIModels } from '@/api/endpoints'
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from '@/components/ui/command'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Slider } from '@/components/ui/slider'
import { Switch } from '@/components/ui/switch'
import { queryKeys } from '@/lib/queryKeys'
import { cn } from '@/lib/utils'
import type { AIModel } from '@/types'

import {
  PARAM_OFF,
  type ParamKey,
  type ParamState,
  type PromptDraft,
} from './agentDraft'

interface ModelTabProps {
  errors: Record<string, string>
  onChange: (prompt: PromptDraft) => void
  value: PromptDraft
}

type ParamControl =
  | { kind: 'field'; placeholder: string }
  | { kind: 'select'; options: { label: string; value: string }[] }
  | { kind: 'slider'; step: number }

const PARAMS: { control: ParamControl; key: ParamKey; label: string }[] = [
  {
    control: { kind: 'field', placeholder: '8192' },
    key: 'maxTokens',
    label: 'Max tokens',
  },
  {
    control: {
      kind: 'select',
      options: [
        { label: 'Off', value: PARAM_OFF },
        { label: '4,096 budget', value: '4096' },
        { label: '16,384 budget', value: '16384' },
      ],
    },
    key: 'thinking',
    label: 'Extended thinking',
  },
  {
    control: {
      kind: 'select',
      options: [
        { label: '5 minutes', value: '5m' },
        { label: '1 hour', value: '1h' },
      ],
    },
    key: 'promptCaching',
    label: 'Prompt caching',
  },
  {
    control: { kind: 'slider', step: 0.1 },
    key: 'temperature',
    label: 'Temperature',
  },
  {
    control: { kind: 'field', placeholder: '40' },
    key: 'topK',
    label: 'Top K',
  },
  { control: { kind: 'slider', step: 0.05 }, key: 'topP', label: 'Top P' },
]

/**
 * Model and model parameters. They are stored in the agent's prompt
 * version in the prompt CMS, not on the agent.
 */
export function ModelTab({ errors, onChange, value }: ModelTabProps) {
  const { data: catalog = [] } = useQuery({
    queryFn: ({ signal }) => listAIModels(signal),
    queryKey: queryKeys.aiModels(),
  })
  const models = useMemo(
    () =>
      catalog.filter(
        (m) =>
          (m.model_type ?? 'generative') === 'generative' &&
          (m.enabled || m.slug === value.model),
      ),
    [catalog, value.model],
  )
  const selected = models.find((m) => m.slug === value.model) ?? null
  const providers = [...new Set(models.map((m) => m.provider_name))].sort()
  const [provider, setProvider] = useState<string>(
    () => selected?.provider_name ?? '',
  )
  const activeProvider =
    provider || selected?.provider_name || providers[0] || ''
  const [advanced, setAdvanced] = useState(() =>
    Object.values(value.params).some((p) => p.on),
  )

  const setParam = (key: ParamKey, patch: Partial<ParamState>) =>
    onChange({
      ...value,
      params: { ...value.params, [key]: { ...value.params[key], ...patch } },
    })

  return (
    <div className="flex max-w-180 flex-col gap-4">
      <div>
        <Label
          className="mb-1.5 block text-sm text-secondary"
          htmlFor="agent-provider"
        >
          LLM provider
        </Label>
        <Select onValueChange={setProvider} value={activeProvider}>
          <SelectTrigger id="agent-provider">
            <SelectValue placeholder="No providers in the catalog" />
          </SelectTrigger>
          <SelectContent>
            {providers.map((p) => (
              <SelectItem key={p} value={p}>
                {p}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <div>
        <Label className="mb-1.5 block text-sm text-secondary">Model</Label>
        <ModelPicker
          models={models.filter((m) => m.provider_name === activeProvider)}
          onChange={(model) => onChange({ ...value, model })}
          selected={selected}
          value={value.model}
        />
        <p className="mt-1.5 text-xs text-tertiary">
          Input / output price per million tokens. The list shows the enabled
          models in the AI Models catalog.
        </p>
      </div>

      <div className="flex">
        <button
          className="ml-auto flex items-center gap-1.5 text-sm text-action hover:underline"
          onClick={() => setAdvanced(!advanced)}
          type="button"
        >
          {advanced ? 'Hide advanced controls' : 'Show advanced controls'}
          {advanced ? (
            <ChevronUp className="size-3.5" />
          ) : (
            <ChevronDown className="size-3.5" />
          )}
        </button>
      </div>

      {advanced && (
        <div className="flex flex-col gap-5 border-t border-border pt-5">
          <div className="grid grid-cols-2 gap-x-6 gap-y-5">
            {PARAMS.map((p) => (
              <ParamRow
                control={p.control}
                error={errors[`param.${p.key}`]}
                key={p.key}
                label={p.label}
                onChange={(patch) => setParam(p.key, patch)}
                state={value.params[p.key]}
              />
            ))}
          </div>
          <p className="text-xs text-tertiary">
            Anything switched off is left unset and the provider default
            applies.
          </p>
        </div>
      )}
    </div>
  )
}

function formatContext(tokens: null | number | undefined): null | string {
  if (!tokens) return null
  return tokens >= 1_000_000
    ? `${tokens / 1_000_000}M`
    : `${Math.round(tokens / 1000)}K`
}

function formatPrice(model: AIModel): null | string {
  if (model.input_cost_per_million == null) return null
  const n = (v: null | number | string | undefined) => `$${Number(v ?? 0)}`
  return `${n(model.input_cost_per_million)} / ${n(model.output_cost_per_million)}`
}

function ModelPicker({
  models,
  onChange,
  selected,
  value,
}: {
  models: AIModel[]
  onChange: (slug: null | string) => void
  selected: AIModel | null
  value: null | string
}) {
  const [open, setOpen] = useState(false)
  const meta = selected
    ? [formatContext(selected.context_window), formatPrice(selected)]
        .filter(Boolean)
        .join(' · ')
    : ''
  return (
    <Popover onOpenChange={setOpen} open={open}>
      <PopoverTrigger asChild>
        <button
          aria-label="Model"
          className="flex h-10 w-full items-center gap-3 rounded-md border border-input bg-card px-3 text-left hover:border-action"
          type="button"
        >
          <span
            className={cn(
              'flex-1 truncate font-mono text-sm',
              !value && 'text-tertiary',
            )}
          >
            {value ?? 'No model selected'}
          </span>
          {meta && (
            <span className="font-mono text-xs text-tertiary tabular-nums">
              {meta}
            </span>
          )}
          <ChevronDown className="size-4 text-tertiary" />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="p-0"
        style={{ width: 'var(--radix-popover-trigger-width)' }}
      >
        <Command>
          <CommandInput placeholder="Search models" />
          <CommandList className="max-h-80">
            <CommandEmpty>No model matches.</CommandEmpty>
            <CommandGroup>
              {value && (
                <CommandItem
                  onSelect={() => {
                    onChange(null)
                    setOpen(false)
                  }}
                  value="__none__"
                >
                  <span className="flex-1 text-sm text-tertiary">No model</span>
                </CommandItem>
              )}
              {models.map((m) => {
                const context = formatContext(m.context_window)
                const price = formatPrice(m)
                return (
                  <CommandItem
                    key={m.id}
                    onSelect={() => {
                      onChange(m.slug)
                      setOpen(false)
                    }}
                    value={`${m.slug} ${m.model_id}`}
                  >
                    <span className="min-w-0 flex-1 truncate font-mono text-sm">
                      {m.slug}
                    </span>
                    {context && (
                      <span className="rounded bg-secondary px-2 py-0.5 font-mono text-xs whitespace-nowrap text-secondary tabular-nums">
                        {context} context
                      </span>
                    )}
                    {price && (
                      <span className="rounded bg-amber-bg px-2 py-0.5 font-mono text-xs whitespace-nowrap text-amber-text tabular-nums">
                        {price}
                      </span>
                    )}
                    <Check
                      className={cn(
                        'size-4 text-action',
                        m.slug === value ? 'opacity-100' : 'opacity-0',
                      )}
                    />
                  </CommandItem>
                )
              })}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  )
}

function ParamRow({
  control,
  error,
  label,
  onChange,
  state,
}: {
  control: ParamControl
  error?: string
  label: string
  onChange: (patch: Partial<ParamState>) => void
  state: ParamState
}) {
  const disabled = !state.on
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-3">
        <span
          className={cn(
            'text-sm font-medium',
            state.on ? 'text-primary' : 'text-tertiary',
          )}
        >
          {label}
        </span>
        <span className="ml-auto">
          <Switch
            aria-label={`${state.on ? 'Disable' : 'Enable'} ${label}`}
            checked={state.on}
            onCheckedChange={(on) => onChange({ on })}
          />
        </span>
      </div>
      <div className={cn('transition-opacity', disabled && 'opacity-45')}>
        {control.kind === 'field' && (
          <Input
            aria-label={label}
            className="h-9 font-mono"
            disabled={disabled}
            inputMode="numeric"
            onChange={(e) => onChange({ value: e.target.value })}
            placeholder={control.placeholder}
            value={state.value}
          />
        )}
        {control.kind === 'select' && (
          <Select
            disabled={disabled}
            onValueChange={(v) => onChange({ value: v })}
            value={state.value}
          >
            <SelectTrigger aria-label={label} className="h-9">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {control.options.map((o) => (
                <SelectItem key={o.value} value={o.value}>
                  {o.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        {control.kind === 'slider' && (
          <div className="flex items-center gap-3">
            <Slider
              aria-label={label}
              className="flex-1"
              disabled={disabled}
              max={1}
              min={0}
              onValueChange={([v]) =>
                onChange({ value: String(Math.round(v * 100) / 100) })
              }
              step={control.step}
              value={[Number(state.value) || 0]}
            />
            <span className="flex h-9 w-16.5 items-center rounded-md border border-input bg-card px-2 font-mono text-sm tabular-nums">
              {state.value}
            </span>
          </div>
        )}
      </div>
      {error && (
        <p className="text-xs text-danger" role="alert">
          {error}
        </p>
      )}
    </div>
  )
}
