import { useState } from 'react'

import { useMutation } from '@tanstack/react-query'
import { Play, Plus, X } from 'lucide-react'
import { toast } from 'sonner'

import { runPrompt } from '@/api/endpoints'
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
import { useOrganization } from '@/contexts/OrganizationContext'
import { extractApiErrorDetail } from '@/lib/apiError'
import type {
  Prompt,
  PromptDecisionQuestion,
  PromptRunResponse,
  PromptVariable,
  PromptVersionCreate,
} from '@/types'

/** One question as the editor holds it, whatever its type. */
export interface QuestionRow {
  id: string
  instructions: string
  levels: string[]
  noulFalse: string
  noulTrue: string
  options: { key: string; text: string }[]
  type: QuestionType
}

interface QuestionsCardProps {
  canEdit: boolean
  onChange: (rows: QuestionRow[]) => void
  rows: QuestionRow[]
}

type QuestionType = PromptDecisionQuestion['type']

interface RunPanelProps {
  /** Errors in the draft; Run is disabled while there are any. */
  blocked: boolean
  content: PromptVersionCreate
  prompt: Prompt
  variables: { name: string; type: PromptVariable['type'] }[]
}

const IDENTIFIER = /^[A-Za-z_][A-Za-z0-9_]*$/

const MAX_OPTIONS = 255

const MIN_LEVELS = 2

const MAX_LEVELS = 10

const CARD = 'bg-primary border-tertiary rounded-lg border'

const CARD_STYLE = { borderWidth: '0.5px' }

const HEADER = 'border-tertiary flex items-center gap-2 border-b px-4 py-2.5'

const HEADER_STYLE = { borderBottomWidth: '0.5px' }

export function newQuestion(id: string): QuestionRow {
  return {
    id,
    instructions: '',
    levels: ['', ''],
    noulFalse: '',
    noulTrue: '',
    options: [{ key: '', text: '' }],
    type: 'noul',
  }
}

export function questionErrors(rows: QuestionRow[]): string[] {
  const errors: string[] = []
  const ids = rows.map((r) => r.id)
  if (ids.some((id) => !IDENTIFIER.test(id))) {
    errors.push('Question ids must be identifiers')
  }
  if (new Set(ids).size !== ids.length) {
    errors.push('Question ids must be unique')
  }
  for (const row of rows) {
    if (row.instructions.trim() === '') {
      errors.push(`Question ${row.id || '?'} needs instructions`)
    }
    if (
      row.type === 'noul' &&
      (row.noulTrue === '') !== (row.noulFalse === '')
    ) {
      errors.push(`Question ${row.id}: describe both yes and no, or neither`)
    }
    if (row.type === 'choice') {
      const keys = row.options.map((o) => o.key)
      if (keys.length < 1 || keys.length > MAX_OPTIONS) {
        errors.push(`Question ${row.id}: 1 to ${MAX_OPTIONS} options`)
      }
      if (
        keys.some((k) => k.trim() === '') ||
        new Set(keys).size !== keys.length
      ) {
        errors.push(`Question ${row.id}: option names must be unique`)
      }
    }
    if (row.type === 'score') {
      if (row.levels.length < MIN_LEVELS || row.levels.length > MAX_LEVELS) {
        errors.push(`Question ${row.id}: ${MIN_LEVELS} to ${MAX_LEVELS} levels`)
      }
      if (row.levels.some((l) => l.trim() === '')) {
        errors.push(`Question ${row.id}: describe every level`)
      }
    }
  }
  return errors
}

export function questionRowsFrom(
  questions: Record<string, PromptDecisionQuestion> | undefined,
): QuestionRow[] {
  return Object.entries(questions ?? {}).map(([id, q]) => {
    const row = newQuestion(id)
    row.type = q.type
    row.instructions = q.instructions
    if (q.type === 'noul' && q.criteria) {
      row.noulTrue = q.criteria.true
      row.noulFalse = q.criteria.false
    } else if (q.type === 'choice') {
      row.options = Object.entries(q.criteria).map(([key, text]) => ({
        key,
        text: text ?? '',
      }))
    } else if (q.type === 'score') {
      row.levels = [...q.criteria]
    }
    return row
  })
}

/** The typed questions of a decision prompt. */
export function QuestionsCard({ canEdit, onChange, rows }: QuestionsCardProps) {
  const update = (i: number, patch: Partial<QuestionRow>) =>
    onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)))
  return (
    <section className={CARD} style={CARD_STYLE}>
      <header className={HEADER} style={HEADER_STYLE}>
        <span className="text-primary text-[15px] font-medium">Questions</span>
        <span className="text-tertiary text-xs">
          Asked about the state; each returns a typed answer
        </span>
        {canEdit && (
          <Button
            className="ml-auto h-7"
            onClick={() =>
              onChange([...rows, newQuestion(`q${rows.length + 1}`)])
            }
            size="sm"
            variant="outline"
          >
            <Plus />
            Add question
          </Button>
        )}
      </header>
      <div className="space-y-3 px-4 py-3">
        {rows.length === 0 && (
          <p className="text-tertiary text-sm">
            No questions. A decision prompt needs at least one to run.
          </p>
        )}
        {rows.map((row, i) => (
          <div
            className="border-tertiary space-y-2 rounded-md border p-3"
            key={i}
            style={CARD_STYLE}
          >
            <div className="flex items-center gap-2">
              <Input
                aria-label={`Question ${i + 1} id`}
                className="h-8 w-40 font-mono text-xs"
                disabled={!canEdit}
                onChange={(e) => update(i, { id: e.target.value })}
                value={row.id}
              />
              <Select
                disabled={!canEdit}
                onValueChange={(type) =>
                  update(i, { type: type as QuestionType })
                }
                value={row.type}
              >
                <SelectTrigger
                  aria-label={`Question ${i + 1} type`}
                  className="h-8 w-28 font-mono text-xs"
                >
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="noul">noul</SelectItem>
                  <SelectItem value="choice">choice</SelectItem>
                  <SelectItem value="score">score</SelectItem>
                </SelectContent>
              </Select>
              <span className="text-tertiary text-xs">
                {row.type === 'noul' && 'yes / no probability'}
                {row.type === 'choice' && 'one of named options'}
                {row.type === 'score' && 'position on ordered levels'}
              </span>
              {canEdit && (
                <Button
                  aria-label={`Remove question ${i + 1}`}
                  className="ml-auto size-8"
                  onClick={() => onChange(rows.filter((_, j) => j !== i))}
                  size="icon"
                  variant="ghost"
                >
                  <X />
                </Button>
              )}
            </div>
            <Textarea
              aria-label={`Question ${i + 1} instructions`}
              className="min-h-14 font-mono text-xs"
              disabled={!canEdit}
              onChange={(e) => update(i, { instructions: e.target.value })}
              placeholder="The judgment to make, e.g. Is {{ service }} down?"
              value={row.instructions}
            />
            <CriteriaEditor
              canEdit={canEdit}
              index={i}
              onChange={(patch) => update(i, patch)}
              row={row}
            />
          </div>
        ))}
      </div>
    </section>
  )
}

export function questionsFrom(
  rows: QuestionRow[],
): Record<string, PromptDecisionQuestion> {
  return Object.fromEntries(
    rows.map((row): [string, PromptDecisionQuestion] => {
      if (row.type === 'choice') {
        return [
          row.id,
          {
            criteria: Object.fromEntries(
              row.options.map((o) => [o.key, o.text === '' ? null : o.text]),
            ),
            instructions: row.instructions,
            type: 'choice',
          },
        ]
      }
      if (row.type === 'score') {
        return [
          row.id,
          {
            criteria: row.levels,
            instructions: row.instructions,
            type: 'score',
          },
        ]
      }
      const criteria =
        row.noulTrue === '' && row.noulFalse === ''
          ? null
          : { false: row.noulFalse, true: row.noulTrue }
      return [
        row.id,
        { criteria, instructions: row.instructions, type: 'noul' },
      ]
    }),
  )
}

/**
 * Runs the draft on screen against its decision model. A run spends
 * provider credit, so only prompt authors see it.
 */
export function RunPanel({
  blocked,
  content,
  prompt,
  variables,
}: RunPanelProps) {
  const { selectedOrganization } = useOrganization()
  const orgSlug = selectedOrganization?.slug
  const [values, setValues] = useState<Record<string, boolean | string>>({})
  const [inputError, setInputError] = useState<null | string>(null)

  const run = useMutation({
    mutationFn: (vars: Record<string, unknown>) =>
      runPrompt(orgSlug!, {
        draft: {
          namespace: prompt.namespace,
          slug: prompt.slug,
          version: content,
        },
        variables: vars,
      }),
    onError: (err) => toast.error(extractApiErrorDetail(err)),
  })

  const submit = () => {
    const vars: Record<string, unknown> = {}
    try {
      for (const v of variables) {
        const value = parseValue(values[v.name] ?? '', v.type)
        if (value !== undefined) vars[v.name] = value
      }
    } catch {
      setInputError('List and object variables must be valid JSON')
      return
    }
    setInputError(null)
    run.mutate(vars)
  }

  return (
    <section className={CARD} style={CARD_STYLE}>
      <header className={HEADER} style={HEADER_STYLE}>
        <span className="text-primary text-[15px] font-medium">Run</span>
        <span className="text-tertiary text-xs">
          Calls the model with the draft on screen; uses provider credit
        </span>
      </header>
      <div className="space-y-3 px-4 py-3">
        {variables.map((v) => (
          <label
            className="text-secondary flex items-center gap-2 text-xs"
            key={v.name}
          >
            <span className="w-32 truncate font-mono">{v.name}</span>
            {v.type === 'bool' ? (
              <Checkbox
                aria-label={`Run variable ${v.name}`}
                checked={values[v.name] === true}
                onCheckedChange={(c) =>
                  setValues((s) => ({ ...s, [v.name]: c === true }))
                }
              />
            ) : (
              <Input
                aria-label={`Run variable ${v.name}`}
                className="h-8 flex-1 font-mono text-xs"
                inputMode={
                  v.type === 'int' || v.type === 'float' ? 'decimal' : undefined
                }
                onChange={(e) =>
                  setValues((s) => ({ ...s, [v.name]: e.target.value }))
                }
                placeholder={
                  v.type === 'list' || v.type === 'object' ? 'JSON' : v.type
                }
                value={String(values[v.name] ?? '')}
              />
            )}
          </label>
        ))}
        <div className="flex items-center gap-2.5">
          <Button
            disabled={blocked || run.isPending || !orgSlug}
            onClick={submit}
            size="sm"
          >
            <Play />
            {run.isPending ? 'Running…' : 'Run'}
          </Button>
          <span className="text-tertiary text-xs">
            {inputError ?? (blocked ? 'Fix the draft before running' : '')}
          </span>
        </div>
        {run.data && <RunResult result={run.data} />}
      </div>
    </section>
  )
}

function AnswerDetail({ answer }: { answer: Record<string, unknown> }) {
  if (answer.type === 'noul') {
    const yes = typeof answer.noul === 'number' ? answer.noul : 0
    return (
      <div className="mt-1.5 flex items-center gap-2">
        <div className="bg-tertiary h-1.5 flex-1 overflow-hidden rounded-full">
          <div
            className="h-full bg-amber-500"
            style={{ width: `${Math.round(yes * 100)}%` }}
          />
        </div>
        <span className="text-primary w-12 text-right font-mono text-xs tabular-nums">
          {percent(answer.noul)}
        </span>
        <span className="text-tertiary text-xs">yes</span>
      </div>
    )
  }
  const probabilities = Object.entries(
    (answer.probabilities ?? {}) as Record<string, number>,
  ).sort((a, b) => b[1] - a[1])
  const legend = (answer.legend ?? {}) as Record<string, string>
  const winner = answer.type === 'choice' ? String(answer.choice) : null
  return (
    <div className="mt-1.5 space-y-1">
      {answer.type === 'score' && (
        <p className="text-primary font-mono text-xs">
          score{' '}
          {typeof answer.score === 'number' ? answer.score.toFixed(2) : '—'}
        </p>
      )}
      {probabilities.map(([key, p]) => (
        <div className="flex items-center gap-2 text-xs" key={key}>
          <span
            className={
              key === winner
                ? 'text-primary w-40 truncate font-mono font-medium'
                : 'text-secondary w-40 truncate font-mono'
            }
          >
            {legend[key] ?? key}
          </span>
          <div className="bg-tertiary h-1.5 flex-1 overflow-hidden rounded-full">
            <div
              className="h-full bg-amber-500"
              style={{ width: `${Math.round(p * 100)}%` }}
            />
          </div>
          <span className="text-secondary w-12 text-right font-mono tabular-nums">
            {percent(p)}
          </span>
        </div>
      ))}
    </div>
  )
}

function CriteriaEditor({
  canEdit,
  index,
  onChange,
  row,
}: {
  canEdit: boolean
  index: number
  onChange: (patch: Partial<QuestionRow>) => void
  row: QuestionRow
}) {
  const label = `Question ${index + 1}`
  if (row.type === 'noul') {
    return (
      <div className="grid grid-cols-2 gap-2">
        <Input
          aria-label={`${label} yes means`}
          className="h-8 font-mono text-xs"
          disabled={!canEdit}
          onChange={(e) => onChange({ noulTrue: e.target.value })}
          placeholder="Yes means… (optional)"
          value={row.noulTrue}
        />
        <Input
          aria-label={`${label} no means`}
          className="h-8 font-mono text-xs"
          disabled={!canEdit}
          onChange={(e) => onChange({ noulFalse: e.target.value })}
          placeholder="No means… (optional)"
          value={row.noulFalse}
        />
      </div>
    )
  }
  if (row.type === 'choice') {
    const set = (j: number, patch: Partial<QuestionRow['options'][number]>) =>
      onChange({
        options: row.options.map((o, k) => (k === j ? { ...o, ...patch } : o)),
      })
    return (
      <div className="space-y-1.5">
        {row.options.map((o, j) => (
          <div className="flex items-center gap-2" key={j}>
            <Input
              aria-label={`${label} option ${j + 1} name`}
              className="h-8 w-40 font-mono text-xs"
              disabled={!canEdit}
              onChange={(e) => set(j, { key: e.target.value })}
              placeholder="name"
              value={o.key}
            />
            <Input
              aria-label={`${label} option ${j + 1} meaning`}
              className="h-8 flex-1 font-mono text-xs"
              disabled={!canEdit}
              onChange={(e) => set(j, { text: e.target.value })}
              placeholder="What it means (optional)"
              value={o.text}
            />
            {canEdit && row.options.length > 1 && (
              <Button
                aria-label={`Remove ${label} option ${j + 1}`}
                className="size-8"
                onClick={() =>
                  onChange({ options: row.options.filter((_, k) => k !== j) })
                }
                size="icon"
                variant="ghost"
              >
                <X />
              </Button>
            )}
          </div>
        ))}
        {canEdit && row.options.length < MAX_OPTIONS && (
          <Button
            className="h-7"
            onClick={() =>
              onChange({ options: [...row.options, { key: '', text: '' }] })
            }
            size="sm"
            variant="ghost"
          >
            <Plus />
            Add option
          </Button>
        )}
      </div>
    )
  }
  return (
    <div className="space-y-1.5">
      {row.levels.map((level, j) => (
        <div className="flex items-center gap-2" key={j}>
          <span className="text-tertiary w-6 text-right font-mono text-xs">
            {j}
          </span>
          <Input
            aria-label={`${label} level ${j}`}
            className="h-8 flex-1 font-mono text-xs"
            disabled={!canEdit}
            onChange={(e) =>
              onChange({
                levels: row.levels.map((l, k) =>
                  k === j ? e.target.value : l,
                ),
              })
            }
            placeholder="Describe this level"
            value={level}
          />
          {canEdit && row.levels.length > MIN_LEVELS && (
            <Button
              aria-label={`Remove ${label} level ${j}`}
              className="size-8"
              onClick={() =>
                onChange({ levels: row.levels.filter((_, k) => k !== j) })
              }
              size="icon"
              variant="ghost"
            >
              <X />
            </Button>
          )}
        </div>
      ))}
      {canEdit && row.levels.length < MAX_LEVELS && (
        <Button
          className="h-7"
          onClick={() => onChange({ levels: [...row.levels, ''] })}
          size="sm"
          variant="ghost"
        >
          <Plus />
          Add level
        </Button>
      )}
    </div>
  )
}

function parseValue(
  raw: boolean | string,
  type: PromptVariable['type'],
): unknown {
  if (type === 'bool') return raw === true
  const text = String(raw)
  if (text.trim() === '') return undefined
  if (type === 'int' || type === 'float') return Number(text)
  if (type === 'list' || type === 'object') return JSON.parse(text)
  return text
}

function percent(value: unknown): string {
  return typeof value === 'number' ? `${Math.round(value * 100)}%` : '—'
}

function RunResult({ result }: { result: PromptRunResponse }) {
  return (
    <div className="space-y-2" data-testid="run-result">
      {Object.entries(result.answers).map(([id, raw]) => {
        const answer = raw as Record<string, unknown>
        return (
          <div
            className="border-tertiary rounded-md border px-3 py-2"
            key={id}
            style={CARD_STYLE}
          >
            <div className="flex items-center gap-2">
              <span className="text-primary font-mono text-xs font-medium">
                {id}
              </span>
              <span className="text-tertiary font-mono text-xs">
                {String(answer.type)}
              </span>
              {answer.confidence !== undefined && (
                <span className="text-tertiary ml-auto text-xs">
                  confidence {percent(answer.confidence)}
                </span>
              )}
            </div>
            <AnswerDetail answer={answer} />
          </div>
        )
      })}
      <p className="text-tertiary text-xs">
        {result.model_id} · {String(result.usage.input_tokens ?? '?')} in /{' '}
        {String(result.usage.output_tokens ?? '?')} out tokens
      </p>
      <details>
        <summary className="text-tertiary cursor-pointer text-xs">
          Rendered request
        </summary>
        <pre className="bg-secondary text-secondary mt-1.5 overflow-x-auto rounded-md p-2.5 font-mono text-[11px]">
          {JSON.stringify(result.request, null, 2)}
        </pre>
      </details>
    </div>
  )
}
