import { useCallback, useState } from 'react'

import type { ProcessGroup, Turn } from './conversationTurns'
import { isError, type TimelineEntry } from './taskTimeline'

export type ConversationMode = 'compact' | 'standard' | 'verbose'

export const CONVERSATION_MODES: ConversationMode[] = [
  'compact',
  'standard',
  'verbose',
]

export const MODE_KEY = 'imbi:agent-task:conversation-mode'

/** No mode and no reader can fold a turn that runs, failed, or was steered. */
export function canCollapseTurn(turn: Turn): boolean {
  return turn.status === 'done' && !turn.steered
}

/** `4s`, `2m 4s`, `1h 3m`. */
export function elapsed(ms: number): string {
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return s % 60 ? `${m}m ${s % 60}s` : `${m}m`
  return m % 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${Math.floor(m / 60)}h`
}

/** Failed calls in the group, subagent calls included. */
export function groupErrors(group: ProcessGroup): number {
  return group.entries.reduce((n, entry) => n + errorsIn(entry), 0)
}

export function groupOpenByDefault(
  group: ProcessGroup,
  turn: Turn,
  mode: ConversationMode,
): boolean {
  if (mode === 'verbose') return true
  if (mode === 'compact') return false
  if (turn.status !== 'running') return false
  const groups = turn.items.filter((item) => item.kind === 'group')
  return groups[groups.length - 1] === group
}

/** `Ran 3 commands, read 2 files, 1 failed`. */
export function groupSummary(group: ProcessGroup): string {
  const counts = new Map<string, number>()
  for (const entry of group.entries) {
    const kind = callKind(entry)
    if (kind) counts.set(kind, (counts.get(kind) ?? 0) + 1)
  }
  const failed = groupErrors(group)
  const parts = PHRASES.filter(([kind]) => counts.has(kind)).map(
    ([kind, one, many]) => {
      const n = counts.get(kind)!
      return n === 1 ? one : many.replace('#', String(n))
    },
  )
  if (failed) parts.push(`${failed} failed`)
  if (!parts.length) {
    if (group.entries.some((e) => e.event?.payload.kind === 'thinking'))
      return 'Thought'
    if (group.entries.some((e) => e.event?.type === 'todos.updated'))
      return 'Updated the plan'
    return 'Worked'
  }
  const text = parts.join(', ')
  return text[0].toUpperCase() + text.slice(1)
}

export function isConversationMode(value: unknown): value is ConversationMode {
  return CONVERSATION_MODES.includes(value as ConversationMode)
}

export function turnOpenByDefault(turn: Turn, mode: ConversationMode): boolean {
  return mode === 'verbose' || !canCollapseTurn(turn)
}

/** What the turn header says: `Worked for 2m 4s`, `Working…`. */
export function turnTitle(turn: Turn): string {
  const ms = turn.stats.durationMs
  if (turn.status === 'running') return 'Working…'
  if (turn.status === 'failed')
    return ms === null ? 'Failed' : `Failed after ${elapsed(ms)}`
  return ms === null ? 'Worked' : `Worked for ${elapsed(ms)}`
}

/** The reader's mode, kept per browser. */
export function useConversationMode(): [
  ConversationMode,
  (mode: ConversationMode) => void,
] {
  const [mode, setMode] = useState<ConversationMode>(() => {
    try {
      const saved = window.localStorage.getItem(MODE_KEY)
      return isConversationMode(saved) ? saved : 'standard'
    } catch {
      return 'standard'
    }
  })
  const update = useCallback((next: ConversationMode) => {
    setMode(next)
    try {
      window.localStorage.setItem(MODE_KEY, next)
    } catch {
      // Storage can be full or blocked; the mode still applies to this page.
    }
  }, [])
  return [mode, update]
}

/**
 * Open state for turns, groups and rows. A reader's click wins over the
 * mode's default and survives a change of mode.
 */
export function useFoldState(): [
  (id: string, byDefault: boolean) => boolean,
  (id: string, open: boolean) => void,
] {
  const [opened, setOpened] = useState(() => new Map<string, boolean>())
  const isOpen = useCallback(
    (id: string, byDefault: boolean) => opened.get(id) ?? byDefault,
    [opened],
  )
  const setOpen = useCallback((id: string, open: boolean) => {
    setOpened((prev) => new Map(prev).set(id, open))
  }, [])
  return [isOpen, setOpen]
}

const PHRASES: [string, string, string][] = [
  ['shell', 'ran a command', 'ran # commands'],
  ['read', 'read a file', 'read # files'],
  ['search', 'searched once', 'searched # times'],
  ['edit', 'edited a file', 'edited # files'],
  ['agent', 'ran a subagent', 'ran # subagents'],
  ['other', 'made a call', 'made # calls'],
]

function callKind(entry: TimelineEntry): null | string {
  if (!entry.event) return 'agent'
  if (entry.event.type !== 'tool.called') return null
  const tool = entry.event.payload.tool
  switch (tool) {
    case 'Agent':
    case 'Task':
      return 'agent'
    case 'Bash':
      return 'shell'
    case 'Edit':
    case 'MultiEdit':
    case 'NotebookEdit':
    case 'Write':
      return 'edit'
    case 'Glob':
    case 'Grep':
    case 'WebSearch':
      return 'search'
    case 'NotebookRead':
    case 'Read':
      return 'read'
  }
  return 'other'
}

function errorsIn(entry: TimelineEntry): number {
  const own = callKind(entry) && isError(entry) ? 1 : 0
  return entry.children.reduce((n, child) => n + errorsIn(child), own)
}
