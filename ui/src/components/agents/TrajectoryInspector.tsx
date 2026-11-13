import {
  type KeyboardEvent,
  type ReactNode,
  type PointerEvent as ReactPointerEvent,
  useRef,
  useState,
} from 'react'

import { Check, ChevronRight, Copy, X } from 'lucide-react'

import { useClipboard } from '@/hooks/useClipboard'
import { cn } from '@/lib/utils'

import { Prose } from './taskEntryViews'
import { KindTag } from './TrajectoryLedger'
import {
  formatDuration,
  type Trajectory,
  type TrajectoryRecord,
  type TrajectoryRequest,
} from './trajectoryModel'

export type Inspected =
  | { record: TrajectoryRecord; type: 'record' }
  | { request: TrajectoryRequest; type: 'request' }

export type InspectorTab =
  | 'Payload'
  | 'Preview'
  | 'Raw'
  | 'Result'
  | 'Summary'
  | 'Timing'
  | 'Usage'

export const MIN_WIDTH = 320
export const MAX_WIDTH = 720
const TABLE_MIN = 280
const STEP = 16

interface UsageTotals {
  cacheRead: number
  cacheWrite: number
  cost: number
  input: number
  output: number
}

/** `2026-10-08 12:00:05.250`. */
export function startedText(ms: number): string {
  const d = new Date(ms)
  const two = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())} ${two(d.getHours())}:${two(d.getMinutes())}:${two(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, '0')}`
}

/** The status DSH shows: Failed, Pending or Completed. */
export function statusOf(inspected: Inspected, live: boolean): string {
  if (inspected.type === 'request')
    return inspected.request.status === 'pending' && live
      ? 'Pending'
      : 'Completed'
  const r = inspected.record
  if (r.error) return 'Failed'
  if (r.endedAt === null && live) return 'Pending'
  if (r.endedAt === null && r.kind !== 'assistant') return 'Did not finish'
  return 'Completed'
}

/** The tabs of what is inspected, in order. */
export function tabsFor(inspected: Inspected): InspectorTab[] {
  if (inspected.type === 'request') return ['Summary', 'Usage', 'Timing']
  switch (inspected.record.kind) {
    case 'subtool':
    case 'tool':
      return ['Summary', 'Payload', 'Result', 'Timing']
    case 'system':
      return ['Summary', 'Raw']
    default:
      return ['Summary', 'Preview', 'Raw']
  }
}

/**
 * The inspector: a resizable side panel with a header, tabs for the
 * selected record or request, and their content.
 */
export function TrajectoryInspector({
  inspected,
  live,
  onClose,
  onSelect,
  onTab,
  tab,
  trajectory,
}: {
  inspected: Inspected
  live: boolean
  onClose: () => void
  onSelect: (target: Inspected) => void
  onTab: (tab: InspectorTab) => void
  tab: InspectorTab
  trajectory: Trajectory
}) {
  const [width, setWidth] = useState<null | number>(null)
  const panel = useRef<HTMLElement>(null)
  const tabs = tabsFor(inspected)
  const current = tabs.includes(tab) ? tab : 'Summary'

  const limit = (w: number) => {
    const split = panel.current?.parentElement?.clientWidth ?? 0
    const max = split ? Math.min(MAX_WIDTH, split - TABLE_MIN) : MAX_WIDTH
    return Math.round(
      Math.min(Math.max(w, MIN_WIDTH), Math.max(max, MIN_WIDTH)),
    )
  }
  const onPointerDown = (e: ReactPointerEvent<HTMLDivElement>) => {
    if (e.button !== 0) return
    e.preventDefault()
    const startX = e.clientX
    const startWidth = panel.current?.getBoundingClientRect().width ?? MIN_WIDTH
    const move = (ev: PointerEvent) =>
      setWidth(limit(startWidth + (startX - ev.clientX)))
    const up = () => {
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
    }
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
  }
  const onKeyDown = (e: KeyboardEvent) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return
    e.preventDefault()
    const now = width ?? panel.current?.getBoundingClientRect().width ?? 0
    setWidth(limit(now + (e.key === 'ArrowLeft' ? STEP : -STEP)))
  }

  const section = location(inspected)
  return (
    <aside
      aria-label="Inspector"
      className="hairline-l relative flex w-[clamp(320px,38%,440px)] max-w-[calc(100%-280px)] shrink-0 flex-col border-(--tj-border-2) bg-(--tj-bg-1) text-[13px] leading-5 max-[760px]:absolute max-[760px]:inset-y-0 max-[760px]:right-0 max-[760px]:z-5 max-[760px]:max-w-none max-[760px]:shadow-[-12px_0_32px_rgba(0,0,0,.14)]"
      ref={panel}
      style={width === null ? undefined : { width }}
    >
      <div
        aria-label="Resize inspector"
        aria-orientation="vertical"
        aria-valuemax={MAX_WIDTH}
        aria-valuemin={MIN_WIDTH}
        aria-valuenow={width ?? undefined}
        className="absolute inset-y-0 -left-1 z-1 w-2 cursor-col-resize outline-none focus-visible:bg-(--tj-business)/30"
        onDoubleClick={() => setWidth(null)}
        onKeyDown={onKeyDown}
        onPointerDown={onPointerDown}
        role="separator"
        tabIndex={0}
        title="Drag to resize. Double-click to reset."
      />
      <header className="hairline-b flex h-10.5 shrink-0 items-center gap-2 border-(--tj-border-2) pr-2 pl-3">
        {inspected.type === 'request' ? (
          <>
            <span className="size-1.25 rounded-full bg-(--tj-label-2)" />
            <span className="font-tj-code text-[12px] leading-4 font-medium">
              Request #{inspected.request.number}
            </span>
          </>
        ) : (
          <KindTag kind={inspected.record.kind} />
        )}
        {section && (
          <span className="font-tj-code truncate text-[11px] leading-4 text-(--tj-label-3)">
            {section}
          </span>
        )}
        <button
          aria-label="Close inspector"
          className="ml-auto flex size-7 items-center justify-center rounded-md text-(--tj-label-3) hover:bg-(--tj-hover) hover:text-(--tj-label-1)"
          onClick={onClose}
          type="button"
        >
          <X className="size-[18px]" strokeWidth={1.5} />
        </button>
      </header>
      <div
        className="hairline-b flex h-8.5 shrink-0 scrollbar-none overflow-x-auto border-(--tj-border-2)"
        role="tablist"
      >
        {tabs.map((name) => (
          <button
            aria-selected={current === name}
            className={cn(
              'relative shrink-0 px-2.25 text-[13px] leading-5 outline-none focus-visible:shadow-[inset_0_0_0_1px_var(--tj-business)]',
              current === name
                ? 'text-(--tj-business)'
                : 'text-(--tj-label-3) hover:text-(--tj-label-1)',
            )}
            key={name}
            onClick={() => onTab(name)}
            role="tab"
            type="button"
          >
            {name}
            {current === name && (
              <span className="absolute inset-x-2.25 bottom-0 h-0.5 bg-(--tj-business)" />
            )}
          </button>
        ))}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto pb-4" role="tabpanel">
        <TabBody
          inspected={inspected}
          live={live}
          onSelect={onSelect}
          onTab={onTab}
          tab={current}
          trajectory={trajectory}
        />
      </div>
    </aside>
  )
}

function CopyButton({ text }: { text: string }) {
  const { copied, copy } = useClipboard({ timeoutMs: 1500 })
  const [failed, setFailed] = useState(false)
  return (
    <button
      aria-label={copied ? 'Copied' : 'Copy'}
      className={cn(
        'flex h-4 w-5 items-center justify-center rounded-[4px] hover:bg-(--tj-hover)',
        failed ? 'text-(--tj-error)' : 'text-(--tj-label-2)',
      )}
      onClick={async () => setFailed(!(await copy(text)))}
      title="Copy"
      type="button"
    >
      {copied ? (
        <Check className="size-3" strokeWidth={1.75} />
      ) : (
        <Copy className="size-3" strokeWidth={1.75} />
      )}
    </button>
  )
}

function Field({
  children,
  label,
  sub,
}: {
  children: ReactNode
  label: string
  sub?: boolean
}) {
  return (
    <div className="grid min-h-[22px] grid-cols-[94px_1fr] items-center px-3.5">
      <dt className={cn('text-(--tj-label-3)', sub && 'pl-3')}>{label}</dt>
      <dd className="min-w-0 truncate">{children}</dd>
    </div>
  )
}

function json(value: unknown): string {
  if (typeof value === 'string') return value
  return JSON.stringify(value ?? null, null, 2)
}

function LinkButton({
  children,
  onClick,
}: {
  children: ReactNode
  onClick: () => void
}) {
  return (
    <button
      className="text-(--tj-business) hover:underline"
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  )
}

function location(inspected: Inspected): string {
  const { step, turn } =
    inspected.type === 'request' ? inspected.request : inspected.record
  return step ? `Turn ${turn} · Step ${step}` : `Turn ${turn}`
}

function Payload({ error, text }: { error?: boolean; text: string }) {
  return (
    <div className="relative">
      <div className="absolute top-2 right-2">
        <CopyButton text={text} />
      </div>
      <pre
        className={cn(
          'overflow-x-auto bg-(--tj-code-bg) p-3.5 pr-9 font-tj-code text-[12px] leading-4.75 wrap-break-word whitespace-pre-wrap',
          error && 'text-(--tj-error)',
        )}
      >
        {text || 'No output'}
      </pre>
    </div>
  )
}

function Preview({ record }: { record: TrajectoryRecord }) {
  const [open, setOpen] = useState(true)
  const { reply, thinking } = record.body
  const text = reply || (thinking ? '' : record.text)
  return (
    <div className="flex flex-col gap-3 px-3.5 pt-3">
      {thinking && (
        <div className="border-l-2 border-(--tj-citation) pl-3">
          <button
            aria-expanded={open}
            className="flex items-center gap-1 text-[12px] leading-[18px] font-semibold text-(--tj-label-2)"
            onClick={() => setOpen(!open)}
            type="button"
          >
            Thinking
            <ChevronRight
              className={cn('size-3 transition-transform', open && 'rotate-90')}
            />
          </button>
          {open && (
            <div className="text-(--tj-label-2)">
              <Prose>{thinking}</Prose>
            </div>
          )}
        </div>
      )}
      {text && <Prose>{text}</Prose>}
      {!text && !thinking && (
        <p className="text-(--tj-label-3)">(tool call only)</p>
      )}
    </div>
  )
}

function Raw({ record }: { record: TrajectoryRecord }) {
  return (
    <div className="flex flex-col gap-3 pt-3">
      {record.events.map((e, i) => (
        <div key={e.event_id}>
          <div className="font-tj-code px-3.5 pb-1 text-[11px] leading-4 text-(--tj-label-3)">
            Block #{i + 1} {e.type} · e{e.seq}
          </div>
          <Payload text={json(e.payload)} />
        </div>
      ))}
    </div>
  )
}

function Section({
  children,
  onOpen,
  title,
}: {
  children: ReactNode
  onOpen: () => void
  title: string
}) {
  return (
    <section className="flex flex-col pt-2">
      <button
        className="flex h-6 items-center gap-1 pb-0.75 pl-3.5 text-[13px] leading-5 font-medium text-(--tj-label-2) hover:text-(--tj-label-1)"
        onClick={onOpen}
        type="button"
      >
        {title}
        <ChevronRight className="size-3 text-(--tj-caption)" />
      </button>
      <div className="max-h-48 overflow-y-auto mask-[linear-gradient(to_bottom,black_calc(100%-12px),transparent)]">
        {children}
      </div>
    </section>
  )
}

function Started({ ms }: { ms: number }) {
  const [unix, setUnix] = useState(false)
  return (
    <button
      className="font-tj-code text-[12px]"
      onClick={() => setUnix(!unix)}
      title="Click to switch format"
      type="button"
    >
      {unix ? (ms / 1000).toFixed(3) : startedText(ms)}
    </button>
  )
}

function TabBody({
  inspected,
  live,
  onSelect,
  onTab,
  tab,
  trajectory,
}: {
  inspected: Inspected
  live: boolean
  onSelect: (target: Inspected) => void
  onTab: (tab: InspectorTab) => void
  tab: InspectorTab
  trajectory: Trajectory
}) {
  if (inspected.type === 'request') {
    const { request } = inspected
    const assistant = trajectory.records.find((r) => r.id === request.assistant)
    if (tab === 'Usage')
      return <UsageView request={request} trajectory={trajectory} />
    if (tab === 'Timing') return <Timing record={assistant} request={request} />
    const usage = request.usage?.payload ?? {}
    return (
      <>
        <dl className="pt-2">
          <Field label="Status">{statusOf(inspected, live)}</Field>
          <Field label="Model">
            {typeof usage.model_id === 'string'
              ? usage.model_id
              : 'Not recorded'}
          </Field>
          <Field label="Tool calls">{request.toolCalls}</Field>
          <Field label="Subtool calls">{request.subtoolCalls}</Field>
          {usage.cost != null && (
            <Field label="Cost">${Number(usage.cost).toFixed(4)}</Field>
          )}
          {assistant && (
            <Field label="Result">
              <LinkButton
                onClick={() => onSelect({ record: assistant, type: 'record' })}
              >
                Assistant Message
              </LinkButton>
            </Field>
          )}
        </dl>
        <Section onOpen={() => onTab('Usage')} title="Usage">
          <UsageView request={request} trajectory={trajectory} />
        </Section>
        <Section onOpen={() => onTab('Timing')} title="Timing">
          <Timing record={assistant} request={request} />
        </Section>
      </>
    )
  }
  const { record } = inspected
  const request = trajectory.requests.find((r) => r.number === record.request)
  const parent = record.parent
    ? trajectory.records.find((r) => r.id === record.parent)
    : undefined
  if (tab === 'Payload')
    return <Payload text={json(record.tool?.arguments ?? {})} />
  if (tab === 'Result')
    return (
      <Payload
        error={record.error}
        text={record.tool ? json(record.tool.resultValue ?? '') : ''}
      />
    )
  if (tab === 'Timing') return <Timing record={record} />
  if (tab === 'Preview') return <Preview record={record} />
  if (tab === 'Raw') return <Raw record={record} />
  const tokens =
    record.kind === 'assistant' && request?.usage
      ? Number(request.usage.payload.tokens_out ?? 0)
      : null
  return (
    <>
      <dl className="pt-2">
        {request && (
          <Field label="Source">
            <LinkButton onClick={() => onSelect({ request, type: 'request' })}>
              Request #{request.number}
            </LinkButton>
          </Field>
        )}
        {parent && (
          <Field label="Hierarchy">
            <LinkButton
              onClick={() => onSelect({ record: parent, type: 'record' })}
            >
              Tool Call
            </LinkButton>
          </Field>
        )}
        <Field label="Status">{statusOf(inspected, live)}</Field>
        {record.tool && <Field label="Tool">{record.tool.tool}</Field>}
        {tokens !== null && (
          <Field label="Tokens">{`${tokens.toLocaleString('en-US')} tok`}</Field>
        )}
        {record.kind !== 'assistant' && !record.tool && (
          <Field label="Time">
            {record.startedAt === null ? (
              'Not recorded'
            ) : (
              <Started ms={record.startedAt} />
            )}
          </Field>
        )}
      </dl>
      {record.tool ? (
        <>
          <Section onOpen={() => onTab('Payload')} title="Payload">
            <Payload text={json(record.tool.arguments ?? {})} />
          </Section>
          <Section onOpen={() => onTab('Result')} title="Result">
            <Payload
              error={record.error}
              text={json(record.tool.resultValue ?? '')}
            />
          </Section>
          <Section onOpen={() => onTab('Timing')} title="Timing">
            <Timing record={record} />
          </Section>
        </>
      ) : record.kind === 'system' ? (
        <Section onOpen={() => onTab('Raw')} title="Raw">
          <Payload text={json(record.events[0]?.payload ?? {})} />
        </Section>
      ) : (
        <>
          <Section onOpen={() => onTab('Preview')} title="Preview">
            <Preview record={record} />
          </Section>
          {record.kind === 'assistant' && request && (
            <Section
              onOpen={() => onSelect({ request, type: 'request' })}
              title="Request Timing"
            >
              <Timing record={record} request={request} />
            </Section>
          )}
        </>
      )}
    </>
  )
}

function Timing({
  record,
  request,
}: {
  record?: TrajectoryRecord
  request?: TrajectoryRequest
}) {
  const startedAt = request?.startedAt ?? record?.startedAt ?? null
  const endedAt = request ? request.endedAt : (record?.endedAt ?? null)
  const total =
    startedAt !== null && endedAt !== null ? endedAt - startedAt : null
  const assistant = !!request || record?.kind === 'assistant'
  return (
    <dl className="pt-2">
      <Field label="Started">
        {startedAt === null ? 'Not recorded' : <Started ms={startedAt} />}
      </Field>
      <Field label={assistant ? 'Total duration' : 'Duration'}>
        {total === null ? 'Pending' : formatDuration(total)}
      </Field>
      {assistant ? (
        <>
          <Field label="TTFT">Not recorded</Field>
          <Field label="Generation">Not recorded</Field>
          <Field label="Throughput">Not recorded</Field>
        </>
      ) : (
        <Field label="Timing source">Session timestamps</Field>
      )}
    </dl>
  )
}

function totals(requests: TrajectoryRequest[]): UsageTotals {
  const sum: UsageTotals = {
    cacheRead: 0,
    cacheWrite: 0,
    cost: 0,
    input: 0,
    output: 0,
  }
  for (const r of requests) {
    const p = r.usage?.payload ?? {}
    sum.input += Number(p.tokens_in ?? 0)
    sum.output += Number(p.tokens_out ?? 0)
    sum.cacheRead += Number(p.cache_read_tokens ?? 0)
    sum.cacheWrite += Number(p.cache_write_tokens ?? 0)
    sum.cost += Number(p.cost ?? 0)
  }
  return sum
}

function UsageGroup({ title, usage }: { title: string; usage: UsageTotals }) {
  const tok = (n: number) => `${n.toLocaleString('en-US')} tok`
  return (
    <div className="pt-2">
      <div className="px-3.5 text-[12px] leading-[18px] font-medium text-(--tj-label-2)">
        {title}
      </div>
      <dl>
        <Field label="Input">
          {tok(usage.input + usage.cacheRead + usage.cacheWrite)}
        </Field>
        <Field label="Cached" sub>
          {tok(usage.cacheRead)}
        </Field>
        <Field label="Cache created" sub>
          {tok(usage.cacheWrite)}
        </Field>
        <Field label="Other" sub>
          {tok(usage.input)}
        </Field>
        <Field label="Output">{tok(usage.output)}</Field>
      </dl>
    </div>
  )
}

function UsageView({
  request,
  trajectory,
}: {
  request: TrajectoryRequest
  trajectory: Trajectory
}) {
  if (!request.usage)
    return <p className="px-3.5 pt-3 text-(--tj-label-3)">Usage unavailable</p>
  const upTo = trajectory.requests.filter((r) => r.number <= request.number)
  return (
    <>
      <UsageGroup title="This request" usage={totals([request])} />
      <UsageGroup title="Session cumulative" usage={totals(upTo)} />
    </>
  )
}
