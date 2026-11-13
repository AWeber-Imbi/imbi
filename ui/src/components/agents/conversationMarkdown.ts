import { elapsed } from './conversationMode'
import type { Turn } from './conversationTurns'
import { formatTokens } from './taskEvents'
import { systemText } from './taskText'
import { isError, type TimelineEntry } from './taskTimeline'
import { isRecord, toolLabel, toolSummary } from './toolCalls'

/**
 * The loaded conversation as Markdown: the person's messages as quotes,
 * the calls as a list, the replies as they are. Thinking is left out.
 */
export function conversationMarkdown(
  task: { description?: string; title?: null | string },
  list: Turn[],
): string {
  const heading =
    task.title || (task.description ?? '').split('\n')[0] || 'Conversation'
  const blocks = [`# ${heading}`]
  list.forEach((turn, i) => {
    blocks.push(`## Turn ${i + 1}`)
    for (const entry of turn.opening) blocks.push(quote(entry))
    let calls: string[] = []
    const flush = () => {
      if (calls.length) blocks.push(calls.join('\n'))
      calls = []
    }
    for (const item of turn.items) {
      if (item.kind === 'group') {
        for (const entry of item.entries)
          calls.push(...callLines(entry, '', turn.status === 'running'))
        continue
      }
      flush()
      const e = item.entry.event
      if (!e) continue
      if (item.kind === 'reply') blocks.push(String(e.payload.body ?? ''))
      else if (item.kind === 'note') blocks.push(`_${systemText(e)}_`)
      else if (e.type === 'request.opened')
        blocks.push(`> **${systemText(e)}**`)
      else blocks.push(quote(item.entry))
    }
    flush()
    const footer = turnFooter(turn)
    if (footer) blocks.push(`*${footer}*`)
  })
  return `${blocks.map((b) => b.trimEnd()).join('\n\n')}\n`
}

/** `2m 4s · 5 tools · 1 failed · 12k tokens`, or null while it runs. */
export function turnFooter(turn: Turn): null | string {
  if (turn.status === 'running') return null
  const { durationMs, errors, tokens, tools } = turn.stats
  const parts: string[] = []
  if (durationMs !== null) parts.push(elapsed(durationMs))
  if (tools) parts.push(`${tools} ${tools === 1 ? 'tool' : 'tools'}`)
  if (errors) parts.push(`${errors} failed`)
  if (tokens) parts.push(`${formatTokens(tokens)} tokens`)
  return parts.length ? parts.join(' · ') : null
}

function callLines(
  entry: TimelineEntry,
  indent: string,
  running: boolean,
): string[] {
  const e = entry.event
  if (e && e.type !== 'tool.called') return []
  const tool = e ? String(e.payload.tool ?? 'tool') : 'Task'
  const args = isRecord(e?.payload.arguments) ? e.payload.arguments : {}
  const pending = running ? 'running…' : 'did not finish'
  const summary = e ? toolSummary(tool, args) : pending
  const line = `${indent}- \`${toolLabel(tool)}\` ${summary}`.trimEnd()
  return [
    isError(entry) ? `${line} — failed` : line,
    ...entry.children.flatMap((child) =>
      callLines(child, `${indent}  `, running),
    ),
  ]
}

function quote(entry: TimelineEntry): string {
  const e = entry.event
  if (!e) return ''
  const body =
    typeof e.payload.body === 'string' && e.payload.body
      ? e.payload.body
      : systemText(e)
  return body
    .split('\n')
    .map((line) => (line ? `> ${line}` : '>'))
    .join('\n')
}
