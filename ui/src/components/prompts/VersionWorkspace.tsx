import { useMemo, useState } from 'react'

import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Cpu, Lock, Plus, Ruler, Thermometer, X } from 'lucide-react'
import { toast } from 'sonner'

import { createPromptVersion } from '@/api/endpoints'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { extractApiErrorDetail } from '@/lib/apiError'
import { queryKeys } from '@/lib/queryKeys'
import type {
  Prompt,
  PromptEvalSummary,
  PromptMessage,
  PromptVariable,
  PromptVersion,
  PromptVersionCreate,
} from '@/types'

import { AIModelSelect } from './AIModelSelect'
import {
  questionErrors,
  type QuestionRow,
  questionRowsFrom,
  QuestionsCard,
  questionsFrom,
  RunPanel,
} from './DecisionEditor'
import { PromptBodyEditor } from './PromptBodyEditor'

const VARIABLE_TYPES: PromptVariable['type'][] = [
  'str',
  'int',
  'float',
  'bool',
  'list',
  'object',
]
const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/

interface Draft {
  maxTokens: string
  messages: PromptMessage[]
  model: null | string
  /** Decision prompts only. */
  questions: QuestionRow[]
  /** Decision prompts only. */
  state: string
  system: string
  temperature: string
  variables: VariableRow[]
}

interface VariableRow {
  description?: null | string
  name: string
  required: boolean
  type: PromptVariable['type']
}

function draftErrors(draft: Draft, decision: boolean): string[] {
  const errors: string[] = decision ? questionErrors(draft.questions) : []
  const temperature = toNumber(draft.temperature)
  if (
    temperature != null &&
    (Number.isNaN(temperature) || temperature < 0 || temperature > 2)
  ) {
    errors.push('Temperature must be between 0 and 2')
  }
  const maxTokens = toNumber(draft.maxTokens)
  if (maxTokens != null && (!Number.isInteger(maxTokens) || maxTokens <= 0)) {
    errors.push('max_tokens must be a positive whole number')
  }
  const names = draft.variables.map((v) => v.name)
  if (names.some((n) => !IDENTIFIER.test(n))) {
    errors.push('Variable names must be identifiers')
  }
  if (new Set(names).size !== names.length) {
    errors.push('Variable names must be unique')
  }
  return errors
}

function draftFrom(version: PromptVersion): Draft {
  return {
    maxTokens: version.params?.max_tokens?.toString() ?? '',
    messages: version.messages.map((m) => ({ ...m })),
    model: version.model ?? null,
    questions: questionRowsFrom(version.questions),
    state: version.state ?? '',
    system: version.system,
    temperature: version.params?.temperature?.toString() ?? '',
    variables: Object.entries(version.variable_schema).map(([name, v]) => ({
      description: v.description,
      name,
      required: v.required,
      type: v.type,
    })),
  }
}

function toNumber(raw: string): null | number {
  return raw.trim() === '' ? null : Number(raw)
}

function toVersion(
  draft: Draft,
  base: PromptVersion,
  summary: string,
  decision: boolean,
): PromptVersionCreate {
  const variableSchema = Object.fromEntries(
    draft.variables.map((v) => [
      v.name,
      { description: v.description, required: v.required, type: v.type },
    ]),
  )
  if (decision) {
    // A decision version has no system prompt, messages, tools, or
    // model parameters; the API rejects them.
    return {
      messages: [],
      model: draft.model,
      params: { stop_sequences: [] },
      questions: questionsFrom(draft.questions),
      state: draft.state,
      summary,
      system: '',
      tools: [],
      variable_schema: variableSchema,
    }
  }
  return {
    messages: draft.messages,
    model: draft.model,
    params: {
      ...base.params,
      max_tokens: toNumber(draft.maxTokens),
      stop_sequences: base.params?.stop_sequences ?? [],
      temperature: toNumber(draft.temperature),
    },
    questions: {},
    state: '',
    summary,
    system: draft.system,
    tools: base.tools,
    variable_schema: variableSchema,
  }
}

const CARD = 'bg-primary border-tertiary rounded-lg border'
const CARD_STYLE = { borderWidth: '0.5px' }

interface VersionWorkspaceProps {
  canEdit: boolean
  onSaved: (n: number) => void
  prompt: Prompt
  version: PromptVersion
}

/**
 * The editable view of one version. Versions are immutable, so saving
 * cuts a new version from whatever is in the editor.
 */
export function VersionWorkspace({
  canEdit,
  onSaved,
  prompt,
  version,
}: VersionWorkspaceProps) {
  const queryClient = useQueryClient()
  const base = useMemo(() => draftFrom(version), [version])
  const [draft, setDraft] = useState<Draft>(base)
  const [summary, setSummary] = useState('')
  const decision = prompt.kind === 'decision'
  const dirty = JSON.stringify(draft) !== JSON.stringify(base)
  const errors = draftErrors(draft, decision)

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) =>
    setDraft((d) => ({ ...d, [key]: value }))

  const save = useMutation({
    mutationFn: () =>
      createPromptVersion(
        prompt.namespace,
        prompt.slug,
        toVersion(draft, version, summary.trim(), decision),
      ),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
    onSuccess: async (saved) => {
      if (saved.n <= prompt.latest_version) {
        toast.info(`No changes — still v${saved.n}`)
      } else {
        toast.success(`Saved ${prompt.ref}@${saved.n}`)
      }
      setSummary('')
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.prompts() }),
        queryClient.invalidateQueries({
          queryKey: queryKeys.promptVersions(prompt.namespace, prompt.slug),
        }),
      ])
      onSaved(saved.n)
    },
  })

  const updateMessage = (i: number, patch: Partial<PromptMessage>) =>
    set(
      'messages',
      draft.messages.map((m, j) => (j === i ? { ...m, ...patch } : m)),
    )
  const updateVariable = (i: number, patch: Partial<VariableRow>) =>
    set(
      'variables',
      draft.variables.map((v, j) => (j === i ? { ...v, ...patch } : v)),
    )

  return (
    <div className="flex min-w-0 flex-1 flex-col gap-3.5">
      {decision ? (
        <>
          <section className={`${CARD} overflow-hidden`} style={CARD_STYLE}>
            <header
              className="border-tertiary flex flex-wrap items-center gap-x-2.5 gap-y-1.5 border-b px-4 py-2.5"
              style={{ borderBottomWidth: '0.5px' }}
            >
              <span className="text-primary text-[15px] font-medium">
                State
              </span>
              <span className="text-tertiary font-mono text-xs">
                {version.ref}
              </span>
              <span className="text-tertiary text-xs">
                Sent as JSON when it renders to an object or array
              </span>
              <span className="text-tertiary ml-auto flex items-center gap-1.5 text-xs whitespace-nowrap">
                <Lock className="size-3" />
                immutable · edit cuts v{prompt.latest_version + 1}
              </span>
            </header>
            <PromptBodyEditor
              ariaLabel="State template"
              onChange={(v) => set('state', v)}
              readOnly={!canEdit}
              value={draft.state}
            />
            <footer
              className="border-tertiary bg-secondary flex flex-wrap items-center gap-4 border-t px-4 py-2.5"
              style={{ borderTopWidth: '0.5px' }}
            >
              <span className="text-secondary flex items-center gap-1.5 text-xs">
                <Cpu className="size-3.5" />
                <AIModelSelect
                  className="w-56"
                  disabled={!canEdit}
                  modelType="decision"
                  onChange={(v) => set('model', v)}
                  value={draft.model}
                />
              </span>
              <span className="text-tertiary ml-auto font-mono text-xs">
                sha {version.content_sha256.slice(0, 8)}
              </span>
            </footer>
          </section>
          <QuestionsCard
            canEdit={canEdit}
            onChange={(rows) => set('questions', rows)}
            rows={draft.questions}
          />
        </>
      ) : (
        <>
          <section className={`${CARD} overflow-hidden`} style={CARD_STYLE}>
            <header
              className="border-tertiary flex flex-wrap items-center gap-x-2.5 gap-y-1.5 border-b px-4 py-2.5"
              style={{ borderBottomWidth: '0.5px' }}
            >
              <span className="text-primary text-[15px] font-medium">Body</span>
              <span className="text-tertiary font-mono text-xs">
                {version.ref}
              </span>
              <span className="text-tertiary ml-auto flex items-center gap-1.5 text-xs whitespace-nowrap">
                <Lock className="size-3" />
                immutable · edit cuts v{prompt.latest_version + 1}
              </span>
            </header>
            <PromptBodyEditor
              ariaLabel="System prompt"
              onChange={(v) => set('system', v)}
              readOnly={!canEdit}
              value={draft.system}
            />
            <footer
              className="border-tertiary bg-secondary flex flex-wrap items-center gap-4 border-t px-4 py-2.5"
              style={{ borderTopWidth: '0.5px' }}
            >
              <span className="text-secondary flex items-center gap-1.5 text-xs">
                <Cpu className="size-3.5" />
                <AIModelSelect
                  className="w-56"
                  disabled={!canEdit}
                  onChange={(v) => set('model', v)}
                  value={draft.model}
                />
              </span>
              <label className="text-secondary flex items-center gap-1.5 text-xs">
                <Thermometer className="size-3.5" />
                <span className="font-mono">temperature</span>
                <Input
                  aria-label="Temperature"
                  className="h-8 w-20 font-mono text-xs"
                  disabled={!canEdit}
                  inputMode="decimal"
                  onChange={(e) => set('temperature', e.target.value)}
                  value={draft.temperature}
                />
              </label>
              <label className="text-secondary flex items-center gap-1.5 text-xs">
                <Ruler className="size-3.5" />
                <span className="font-mono">max_tokens</span>
                <Input
                  aria-label="Max tokens"
                  className="h-8 w-24 font-mono text-xs"
                  disabled={!canEdit}
                  inputMode="numeric"
                  onChange={(e) => set('maxTokens', e.target.value)}
                  value={draft.maxTokens}
                />
              </label>
              <span className="text-tertiary ml-auto font-mono text-xs">
                sha {version.content_sha256.slice(0, 8)}
              </span>
            </footer>
          </section>

          <section className={CARD} style={CARD_STYLE}>
            <header
              className="border-tertiary flex items-center gap-2 border-b px-4 py-2.5"
              style={{ borderBottomWidth: '0.5px' }}
            >
              <span className="text-primary text-[15px] font-medium">
                Messages
              </span>
              <span className="text-tertiary text-xs">
                Sent after the system prompt
              </span>
              {canEdit && (
                <Button
                  className="ml-auto h-7"
                  onClick={() =>
                    set('messages', [
                      ...draft.messages,
                      { content: '', role: 'user' },
                    ])
                  }
                  size="sm"
                  variant="outline"
                >
                  <Plus />
                  Add message
                </Button>
              )}
            </header>
            <div className="space-y-2 px-4 py-3">
              {draft.messages.length === 0 && (
                <p className="text-tertiary text-sm">No messages.</p>
              )}
              {draft.messages.map((m, i) => (
                <div className="flex items-start gap-2" key={i}>
                  <Select
                    disabled={!canEdit}
                    onValueChange={(role) =>
                      updateMessage(i, { role: role as PromptMessage['role'] })
                    }
                    value={m.role}
                  >
                    <SelectTrigger
                      aria-label={`Message ${i + 1} role`}
                      className="h-8 w-28 font-mono text-xs"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="user">user</SelectItem>
                      <SelectItem value="assistant">assistant</SelectItem>
                    </SelectContent>
                  </Select>
                  <Textarea
                    aria-label={`Message ${i + 1} content`}
                    className="min-h-16 flex-1 font-mono text-xs"
                    disabled={!canEdit}
                    onChange={(e) =>
                      updateMessage(i, { content: e.target.value })
                    }
                    value={m.content}
                  />
                  {canEdit && (
                    <Button
                      aria-label={`Remove message ${i + 1}`}
                      className="size-8"
                      onClick={() =>
                        set(
                          'messages',
                          draft.messages.filter((_, j) => j !== i),
                        )
                      }
                      size="icon"
                      variant="ghost"
                    >
                      <X />
                    </Button>
                  )}
                </div>
              ))}
            </div>
          </section>
        </>
      )}

      <div className="grid grid-cols-1 gap-3.5 lg:grid-cols-2">
        <section className={CARD} style={CARD_STYLE}>
          <header
            className="border-tertiary flex items-center gap-2 border-b px-4 py-2.5"
            style={{ borderBottomWidth: '0.5px' }}
          >
            <span className="text-primary text-[15px] font-medium">
              Variables
            </span>
            {canEdit && (
              <Button
                className="ml-auto h-7"
                onClick={() =>
                  set('variables', [
                    ...draft.variables,
                    { name: '', required: false, type: 'str' },
                  ])
                }
                size="sm"
                variant="outline"
              >
                <Plus />
                Add
              </Button>
            )}
          </header>
          <div className="px-4 py-2">
            {draft.variables.length === 0 && (
              <p className="text-tertiary py-2 text-sm">
                No variables. Renders take no input.
              </p>
            )}
            {draft.variables.map((v, i) => (
              <div
                className="border-tertiary flex items-center gap-2 border-b py-1.5 last:border-b-0"
                key={i}
                style={{ borderBottomWidth: '0.5px' }}
              >
                <Input
                  aria-label={`Variable ${i + 1} name`}
                  className="h-8 flex-1 font-mono text-xs"
                  disabled={!canEdit}
                  onChange={(e) => updateVariable(i, { name: e.target.value })}
                  value={v.name}
                />
                <Select
                  disabled={!canEdit}
                  onValueChange={(type) =>
                    updateVariable(i, {
                      type: type as PromptVariable['type'],
                    })
                  }
                  value={v.type}
                >
                  <SelectTrigger
                    aria-label={`Variable ${i + 1} type`}
                    className="h-8 w-24 font-mono text-xs"
                  >
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {VARIABLE_TYPES.map((t) => (
                      <SelectItem key={t} value={t}>
                        {t}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <label className="text-secondary flex items-center gap-1.5 text-xs">
                  <Checkbox
                    checked={v.required}
                    disabled={!canEdit}
                    onCheckedChange={(c) =>
                      updateVariable(i, { required: c === true })
                    }
                  />
                  required
                </label>
                {canEdit && (
                  <Button
                    aria-label={`Remove variable ${i + 1}`}
                    className="size-8"
                    onClick={() =>
                      set(
                        'variables',
                        draft.variables.filter((_, j) => j !== i),
                      )
                    }
                    size="icon"
                    variant="ghost"
                  >
                    <X />
                  </Button>
                )}
              </div>
            ))}
          </div>
        </section>
        <EvaluationPanel summary={version.eval_summary} />
      </div>

      {decision && canEdit && (
        <RunPanel
          blocked={errors.length > 0 || draft.questions.length === 0}
          content={toVersion(draft, version, '', true)}
          prompt={prompt}
          variables={draft.variables}
        />
      )}

      {canEdit && (
        <div className="flex flex-wrap items-center gap-2.5 pt-1">
          <Input
            aria-label="Change summary"
            className="h-9 max-w-md flex-1"
            onChange={(e) => setSummary(e.target.value)}
            placeholder="What changed in this version?"
            value={summary}
          />
          <Button
            disabled={
              !dirty ||
              summary.trim() === '' ||
              errors.length > 0 ||
              save.isPending
            }
            onClick={() => save.mutate()}
            size="sm"
          >
            Save version
          </Button>
          {dirty && (
            <Button onClick={() => setDraft(base)} size="sm" variant="ghost">
              Discard
            </Button>
          )}
          <span className="text-tertiary ml-auto text-xs">
            {errors[0] ??
              (dirty ? `Saves as v${prompt.latest_version + 1}` : 'No changes')}
          </span>
        </div>
      )}
    </div>
  )
}

function EvaluationPanel({
  summary,
}: {
  summary: PromptVersion['eval_summary']
}) {
  const evaluation = summary as null | PromptEvalSummary | undefined
  return (
    <section className={CARD} style={CARD_STYLE}>
      <header
        className="border-tertiary flex items-center gap-2 border-b px-4 py-2.5"
        style={{ borderBottomWidth: '0.5px' }}
      >
        <span className="text-primary text-[15px] font-medium">
          Latest evaluation
        </span>
        {evaluation && (
          <Badge variant={verdictVariant(evaluation.verdict)}>
            {evaluation.verdict}
          </Badge>
        )}
      </header>
      <div className="px-4 py-2">
        {!evaluation ? (
          <p className="text-tertiary py-2 text-sm">
            No evaluation recorded for this version.
          </p>
        ) : (
          <>
            {evaluation.summary && (
              <p className="text-secondary py-1.5 text-sm">
                {evaluation.summary}
              </p>
            )}
            {evaluation.metrics.map((m) => (
              <div
                className="border-tertiary flex items-center gap-2.5 border-b py-2 last:border-b-0"
                key={m.label}
                style={{ borderBottomWidth: '0.5px' }}
              >
                <span className="text-secondary text-sm">{m.label}</span>
                <span className="text-primary ml-auto font-mono text-sm tabular-nums">
                  {m.value}
                </span>
                {m.delta && (
                  <span className="text-tertiary w-10 text-right font-mono text-xs">
                    {m.delta}
                  </span>
                )}
              </div>
            ))}
            <p className="text-tertiary pt-2 text-xs">
              Cached summary
              {evaluation.run_id ? ` · run ${evaluation.run_id}` : ''} ·
              promotion is never gated on this.
            </p>
          </>
        )}
      </div>
    </section>
  )
}

function verdictVariant(verdict: PromptEvalSummary['verdict']) {
  if (verdict === 'pass') return 'success' as const
  if (verdict === 'fail') return 'danger' as const
  return 'warning' as const
}
