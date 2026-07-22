import { useState } from 'react'

import { Check, GitBranch, Plus, Trash2, X } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import type {
  AttributeCondition,
  Condition,
  ConditionOp,
  RelationshipCondition,
} from '@/types'

// A structural view of a node used by the mutation helpers. Exactly one of
// these keys is populated on a valid node (see imbi-common's Condition model).
interface CondRecord {
  all?: Condition[]
  any?: Condition[]
  attribute?: string
  not?: Condition
  op?: ConditionOp
  relationship?: RelationshipCondition['relationship']
  value?: unknown
}

// Path into the condition tree: numbers index into an all/any array; the
// markers 'not' / 'where' step into a not child or a relationship's where.
type PathSegment = number | string

type Quantifier = 'all' | 'any' | 'none'

const OPS: Array<[ConditionOp, string]> = [
  ['eq', 'is'],
  ['ne', 'is not'],
  ['gt', '>'],
  ['ge', '≥'],
  ['lt', '<'],
  ['le', '≤'],
  ['present', 'is present'],
  ['absent', 'is absent'],
]

const OP_LABELS: Record<ConditionOp, string> = Object.fromEntries(
  OPS,
) as Record<ConditionOp, string>

const QUANTIFIER_PHRASES: Record<Quantifier, string> = {
  all: 'every outgoing dependency',
  any: 'at least one outgoing dependency',
  none: 'no outgoing dependency',
}

// Plain-language semantics, including the easily-missed empty-set behaviour.
const QUANTIFIER_HINTS: Record<Quantifier, string> = {
  all: 'True only when every dependency matches — also true for projects with no dependencies.',
  any: 'True when at least one dependency matches — false for projects with no dependencies.',
  none: 'True when no dependency matches — also true for projects with no dependencies. Use this to penalize projects that have a matching dependency.',
}

const NUMERIC_OPS = new Set<ConditionOp>(['ge', 'gt', 'le', 'lt'])
const NO_VALUE_OPS = new Set<ConditionOp>(['absent', 'present'])

export const DEFAULT_CONDITION: Condition = {
  relationship: {
    direction: 'outgoing',
    edge: 'DEPENDS_ON',
    quantifier: 'none',
    where: { attribute: 'deprecated', op: 'eq', value: true },
  },
}

interface ConditionBuilderProps {
  disabled?: boolean
  falseScore: number
  onChange: (value: Condition) => void
  trueScore: number
  value: Condition
  weight: number
}

export function ConditionBuilder({
  disabled = false,
  falseScore,
  onChange,
  trueScore,
  value,
  weight,
}: ConditionBuilderProps) {
  const [mode, setMode] = useState<'json' | 'visual'>('visual')
  const [jsonDraft, setJsonDraft] = useState(() =>
    JSON.stringify(value, null, 2),
  )
  const [jsonError, setJsonError] = useState('')

  const update = (path: PathSegment[], fn: (node: Condition) => Condition) =>
    onChange(withUpdated(value, path, fn))

  const setAttr = (path: PathSegment[], attribute: string) =>
    update(path, (t) => ({ ...(t as AttributeCondition), attribute }))

  const setOp = (path: PathSegment[], op: ConditionOp) =>
    update(path, (t) => {
      const r = { ...asRecord(t), op }
      if (NO_VALUE_OPS.has(op)) delete r.value
      else if (r.value == null) r.value = ''
      return r as Condition
    })

  const setValue = (path: PathSegment[], v: unknown) =>
    update(path, (t) => ({ ...(t as AttributeCondition), value: v }))

  const setQuantifier = (path: PathSegment[], quantifier: Quantifier) =>
    update(path, (t) => {
      const r = asRecord(t)
      if (r.relationship) r.relationship.quantifier = quantifier
      return t
    })

  const setCombinator = (path: PathSegment[], type: 'all' | 'any') =>
    update(path, (t) => {
      const r = asRecord(t)
      const kids = r.all ?? r.any ?? []
      const next: Condition = type === 'all' ? { all: kids } : { any: kids }
      return next
    })

  const wrap = (path: PathSegment[], type: 'all' | 'any') =>
    update(path, (t) => {
      const next: Condition =
        type === 'all'
          ? { all: [t, defaultRule()] }
          : { any: [t, defaultRule()] }
      return next
    })

  const addChild = (path: PathSegment[], node: Condition) =>
    update(path, (t) => {
      const r = asRecord(t)
      if (r.all) r.all.push(node)
      else if (r.any) r.any.push(node)
      return t
    })

  const deleteChild = (path: PathSegment[], idx: number) =>
    update(path, (t) => {
      const r = asRecord(t)
      const arr = r.all ?? r.any
      if (arr) arr.splice(idx, 1)
      return t
    })

  const switchMode = (next: 'json' | 'visual') => {
    if (next === 'json') {
      setJsonDraft(JSON.stringify(value, null, 2))
      setJsonError('')
    }
    setMode(next)
  }

  const onJsonChange = (text: string) => {
    setJsonDraft(text)
    try {
      const parsed = normalizeCondition(JSON.parse(text) as Condition)
      setJsonError('')
      onChange(parsed)
    } catch (e) {
      setJsonError(e instanceof Error ? e.message : String(e))
    }
  }

  // ---- renderers ----
  const renderValue = (node: Condition, path: PathSegment[]) => {
    const n = asRecord(node)
    const op = (n.op ?? 'eq') as ConditionOp
    if (NO_VALUE_OPS.has(op)) {
      return (
        <span className="text-tertiary px-1 text-xs italic">(no value)</span>
      )
    }
    if (typeof n.value === 'boolean') {
      return (
        <div className="border-input flex overflow-hidden rounded-md border">
          {[true, false].map((b) => (
            <button
              className={`px-3 py-1.5 font-mono text-xs font-semibold ${
                n.value === b
                  ? 'bg-amber-bg text-amber-text'
                  : 'text-secondary hover:bg-secondary'
              }`}
              disabled={disabled}
              key={String(b)}
              onClick={() => setValue(path, b)}
              type="button"
            >
              {String(b)}
            </button>
          ))}
        </div>
      )
    }
    const numeric = NUMERIC_OPS.has(op)
    return (
      <Input
        className="h-9 w-36 font-mono"
        disabled={disabled}
        onChange={(e) => setValue(path, e.target.value)}
        placeholder="value"
        type={numeric ? 'number' : 'text'}
        value={n.value == null ? '' : String(n.value)}
      />
    )
  }

  const opSelect = (node: Condition, path: PathSegment[]) => {
    const n = asRecord(node)
    return (
      <Select
        disabled={disabled}
        onValueChange={(v) => setOp(path, v as ConditionOp)}
        value={n.op ?? 'eq'}
      >
        <SelectTrigger className="h-9 w-auto font-mono">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {OPS.map(([v, label]) => (
            <SelectItem key={v} value={v}>
              {label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    )
  }

  const deleteButton = (onDelete: () => void) => (
    <Button
      className="ml-auto"
      disabled={disabled}
      onClick={onDelete}
      size="icon"
      type="button"
      variant="ghost"
    >
      <Trash2 className="text-tertiary size-4" />
    </Button>
  )

  const wrapButtons = (path: PathSegment[]) => (
    <span className="ml-auto flex gap-1.5">
      {(['all', 'any'] as const).map((type) => (
        <button
          className="border-input text-secondary hover:bg-secondary inline-flex items-center gap-1 rounded-md border px-2.5 py-1.5 text-[11px] font-bold tracking-wider"
          disabled={disabled}
          key={type}
          onClick={() => wrap(path, type)}
          type="button"
        >
          <Plus className="size-3" />
          {type === 'all' ? 'AND' : 'OR'}
        </button>
      ))}
    </span>
  )

  const renderAttr = (
    node: Condition,
    path: PathSegment[],
    slot: 'array' | 'single',
    onDelete: (() => void) | null,
  ) => {
    const n = asRecord(node)
    return (
      <div className="border-input bg-primary flex flex-wrap items-center gap-2 rounded-md border px-3 py-2.5">
        <Input
          className="h-9 w-40 font-mono"
          disabled={disabled}
          onChange={(e) => setAttr(path, e.target.value)}
          placeholder="attribute"
          value={n.attribute ?? ''}
        />
        {opSelect(node, path)}
        {renderValue(node, path)}
        {slot === 'array' && onDelete
          ? deleteButton(onDelete)
          : wrapButtons(path)}
      </div>
    )
  }

  const renderCombinator = (
    node: Condition,
    path: PathSegment[],
    slot: 'array' | 'single',
    onDelete: (() => void) | null,
    inRel: boolean,
  ) => {
    const n = asRecord(node)
    const type: 'all' | 'any' = n.all ? 'all' : 'any'
    const kids = (n.all ?? n.any) as Condition[]
    const conj = type === 'all' ? 'AND' : 'OR'
    return (
      <div className="border-input bg-secondary rounded-lg border p-3.5">
        <div className="mb-3 flex items-center gap-3">
          <span className="border-input flex overflow-hidden rounded-md border">
            {(['all', 'any'] as const).map((t) => (
              <button
                className={`px-3 py-1.5 text-xs font-bold tracking-wide ${
                  type === t
                    ? 'bg-amber-bg text-amber-text'
                    : 'text-secondary hover:bg-primary'
                }`}
                disabled={disabled}
                key={t}
                onClick={() => setCombinator(path, t)}
                type="button"
              >
                {t.toUpperCase()}
              </button>
            ))}
          </span>
          <span className="text-secondary text-sm">
            {type === 'all'
              ? 'of these must be true'
              : 'of these are true (at least one)'}
          </span>
          {slot === 'array' && onDelete ? deleteButton(onDelete) : null}
        </div>
        <div className="border-tertiary ml-2 flex flex-col gap-2 border-l-2 pl-3.5">
          {kids.length === 0 ? (
            <div className="text-tertiary text-xs italic">
              No conditions yet
            </div>
          ) : (
            kids.map((child, i) => (
              <div key={i}>
                {i > 0 && (
                  <span className="bg-amber-bg text-amber-text mb-2 inline-block rounded px-1.5 py-0.5 font-mono text-[10px] font-bold tracking-widest">
                    {conj}
                  </span>
                )}
                {renderNode(
                  child,
                  [...path, i],
                  'array',
                  () => deleteChild(path, i),
                  inRel,
                )}
              </div>
            ))
          )}
        </div>
        <div className="mt-3 ml-2 flex flex-wrap gap-2">
          <AddButton
            disabled={disabled}
            label="Rule"
            onClick={() => addChild(path, defaultRule())}
          />
          <AddButton
            disabled={disabled}
            label="Group"
            onClick={() => addChild(path, defaultGroup())}
          />
          {!inRel && (
            <AddButton
              disabled={disabled}
              label="Dependencies"
              onClick={() => addChild(path, defaultRelationship())}
            />
          )}
        </div>
      </div>
    )
  }

  const renderNot = (
    node: Condition,
    path: PathSegment[],
    slot: 'array' | 'single',
    onDelete: (() => void) | null,
    inRel: boolean,
  ) => (
    <div className="border-input bg-secondary rounded-lg border p-3.5">
      <div className="mb-3 flex items-center gap-3">
        <span className="border-danger bg-danger text-danger inline-flex rounded border px-2 py-1 font-mono text-[11px] font-bold tracking-wider">
          NOT
        </span>
        <span className="text-secondary text-sm">the following is true</span>
        {slot === 'array' && onDelete ? deleteButton(onDelete) : null}
      </div>
      <div className="border-tertiary ml-2 border-l-2 pl-3.5">
        {renderNode(
          childOf(node, 'not'),
          [...path, 'not'],
          'single',
          null,
          inRel,
        )}
      </div>
    </div>
  )

  const renderRelationship = (
    node: Condition,
    path: PathSegment[],
    slot: 'array' | 'single',
    onDelete: (() => void) | null,
  ) => {
    const rel = (node as RelationshipCondition).relationship
    return (
      <div className="border-input bg-primary overflow-hidden rounded-lg border">
        <div className="border-input bg-amber-bg flex flex-wrap items-center gap-2.5 border-b px-3.5 py-3">
          <GitBranch className="text-amber-text size-4" />
          <span className="text-sm font-semibold">Outgoing dependencies</span>
          <span className="border-amber-text bg-amber-bg text-amber-text rounded border px-2 py-0.5 font-mono text-[11px] font-semibold">
            DEPENDS_ON
          </span>
          <span className="border-input bg-secondary text-secondary rounded border px-2 py-0.5 font-mono text-[11px] font-semibold">
            outgoing
          </span>
          {slot === 'array' && onDelete ? deleteButton(onDelete) : null}
        </div>
        <div className="border-input flex flex-wrap items-center gap-2 border-b px-3.5 py-3">
          <span className="text-secondary text-sm">Match when</span>
          <Select
            disabled={disabled}
            onValueChange={(v) => setQuantifier(path, v as Quantifier)}
            value={rel.quantifier}
          >
            <SelectTrigger className="h-9 w-auto font-mono">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {(['any', 'all', 'none'] as const).map((q) => (
                <SelectItem key={q} value={q}>
                  {q}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <span className="text-secondary text-sm">
            of the dependencies match:
          </span>
          <span className="text-tertiary w-full text-xs">
            {QUANTIFIER_HINTS[rel.quantifier]}
          </span>
        </div>
        <div className="p-3.5">
          <div className="border-tertiary ml-2 border-l-2 pl-3.5">
            {renderNode(rel.where, [...path, 'where'], 'single', null, true)}
          </div>
        </div>
      </div>
    )
  }

  function renderNode(
    node: Condition,
    path: PathSegment[],
    slot: 'array' | 'single',
    onDelete: (() => void) | null,
    inRel: boolean,
  ): React.ReactNode {
    const n = asRecord(node)
    if (n.all != null || n.any != null) {
      return renderCombinator(node, path, slot, onDelete, inRel)
    }
    if (n.not != null) return renderNot(node, path, slot, onDelete, inRel)
    if (n.relationship != null) {
      return renderRelationship(node, path, slot, onDelete)
    }
    return renderAttr(node, path, slot, onDelete)
  }

  const modeButton = (m: 'json' | 'visual', label: string) => (
    <button
      className={`px-3.5 py-1.5 text-xs font-semibold ${
        mode === m
          ? 'bg-amber-bg text-amber-text'
          : 'text-secondary hover:bg-secondary'
      }`}
      disabled={disabled}
      onClick={() => switchMode(m)}
      type="button"
    >
      {label}
    </button>
  )

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <span className="border-input flex overflow-hidden rounded-md border">
          {modeButton('visual', 'Visual builder')}
          {modeButton('json', 'JSON')}
        </span>
      </div>

      {mode === 'visual' ? (
        renderNode(value, [], 'single', null, false)
      ) : (
        <div>
          <textarea
            className={`bg-primary w-full resize-y rounded-lg border p-4 font-mono text-xs leading-relaxed outline-none ${
              jsonError ? 'border-danger' : 'border-input'
            }`}
            disabled={disabled}
            onChange={(e) => onJsonChange(e.target.value)}
            rows={14}
            spellCheck={false}
            value={jsonDraft}
          />
          {jsonError ? (
            <div className="text-danger mt-2 flex items-center gap-1.5 font-mono text-xs">
              <X className="size-3.5" />
              Invalid JSON — {jsonError}
            </div>
          ) : (
            <div className="text-success mt-2 flex items-center gap-1.5 text-xs">
              <Check className="size-3.5" />
              Valid condition tree
            </div>
          )}
        </div>
      )}

      <div className="border-input bg-primary rounded-lg border p-4">
        <div className="text-tertiary mb-2 text-[11px] font-semibold tracking-wider uppercase">
          Reads as
        </div>
        <div className="text-sm leading-relaxed">
          {conditionToEnglish(value)}
        </div>
        <div className="text-secondary mt-3 text-xs leading-relaxed">
          Projects where this is true score{' '}
          <span className="text-success font-mono font-semibold">
            {trueScore}
          </span>
          ; every other project scores{' '}
          <span className="text-danger font-mono font-semibold">
            {falseScore}
          </span>
          .
        </div>
        <div className="text-secondary mt-1.5 flex flex-wrap items-center gap-1.5 text-xs">
          <span>Weighted</span>
          <span className="text-amber-text font-mono font-semibold">
            {weight}
          </span>
          <span>in the overall score.</span>
        </div>
      </div>
    </div>
  )
}

// Render the tree as a plain-English sentence for the preview pane.
export function conditionToEnglish(node: Condition): string {
  const n = asRecord(node)
  if (n.all != null) {
    return `(${n.all.map(conditionToEnglish).join(' AND ') || 'always'})`
  }
  if (n.any != null) {
    return `(${n.any.map(conditionToEnglish).join(' OR ') || 'never'})`
  }
  if (n.not != null) return `NOT ${conditionToEnglish(n.not)}`
  if (n.relationship != null) {
    const phrase = QUANTIFIER_PHRASES[n.relationship.quantifier]
    return `${phrase} where ${conditionToEnglish(n.relationship.where)}`
  }
  const op = (n.op ?? 'eq') as ConditionOp
  const label = OP_LABELS[op] ?? op
  if (NO_VALUE_OPS.has(op)) return `${n.attribute || '?'} ${label}`
  return `${n.attribute || '?'} ${label} ${JSON.stringify(n.value)}`
}

// Collapse an arbitrary (possibly null-padded) node into its canonical
// single-key shape. Used when loading a stored policy condition.
export function normalizeCondition(node: Condition): Condition {
  const n = asRecord(node)
  if (n.all != null) return { all: n.all.map(normalizeCondition) }
  if (n.any != null) return { any: n.any.map(normalizeCondition) }
  if (n.not != null) return { not: normalizeCondition(n.not) }
  if (n.relationship != null) {
    return {
      relationship: {
        direction: 'outgoing',
        edge: 'DEPENDS_ON',
        quantifier: n.relationship.quantifier,
        where: normalizeCondition(n.relationship.where),
      },
    }
  }
  const op = n.op ?? 'eq'
  const leaf: AttributeCondition = { attribute: n.attribute ?? '', op }
  if (!NO_VALUE_OPS.has(op)) leaf.value = n.value ?? ''
  return leaf
}

function AddButton({
  disabled,
  label,
  onClick,
}: {
  disabled?: boolean
  label: string
  onClick: () => void
}) {
  return (
    <button
      className="border-tertiary text-secondary hover:bg-secondary inline-flex items-center gap-1.5 rounded-lg border border-dashed px-3 py-1.5 text-xs"
      disabled={disabled}
      onClick={onClick}
      type="button"
    >
      <Plus className="size-3.5" />
      {label}
    </button>
  )
}

// ---- tree shape helpers (tolerant of null siblings from the API) ----
function asRecord(node: Condition): CondRecord {
  return node as CondRecord
}

function childOf(node: Condition, key: PathSegment): Condition {
  const n = asRecord(node)
  if (n.all) return n.all[key as number]
  if (n.any) return n.any[key as number]
  if (n.not != null) return n.not
  return (n.relationship as RelationshipCondition['relationship']).where
}

function clone<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T
}

function defaultGroup(): Condition {
  return { all: [defaultRule()] }
}

function defaultRelationship(): Condition {
  return {
    relationship: {
      direction: 'outgoing',
      edge: 'DEPENDS_ON',
      quantifier: 'none',
      where: defaultRule(),
    },
  }
}

function defaultRule(): AttributeCondition {
  return { attribute: '', op: 'eq', value: '' }
}

function setChild(node: Condition, key: PathSegment, val: Condition): void {
  const n = asRecord(node)
  if (n.all) n.all[key as number] = val
  else if (n.any) n.any[key as number] = val
  else if (n.not != null) n.not = val
  else if (n.relationship) n.relationship.where = val
}

function withUpdated(
  root: Condition,
  path: PathSegment[],
  fn: (node: Condition) => Condition,
): Condition {
  const next = clone(root)
  if (path.length === 0) return fn(next)
  let parent = next
  for (let i = 0; i < path.length - 1; i += 1) parent = childOf(parent, path[i])
  const key = path[path.length - 1]
  setChild(parent, key, fn(clone(childOf(parent, key))))
  return next
}
