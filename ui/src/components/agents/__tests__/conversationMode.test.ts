import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  canCollapseTurn,
  elapsed,
  groupOpenByDefault,
  groupSummary,
  MODE_KEY,
  turnOpenByDefault,
  turnTitle,
  useConversationMode,
  useFoldState,
} from '../conversationMode'
import { type ProcessGroup, type Turn, turns } from '../conversationTurns'
import { timeline } from '../taskTimeline'
import { event } from './taskFixtures'

const human = (seq: number) =>
  event(seq, 'turn', { body: 'Go.' }, { actor_id: 'dev', actor_kind: 'human' })
const call = (seq: number, tool: string, extra: Record<string, unknown> = {}) =>
  event(seq, 'tool.called', {
    arguments: {},
    call_id: `c${seq}`,
    result: 'ok',
    tool,
    ...extra,
  })

function firstTurn(live: boolean, steer = false): Turn {
  const log = [human(1), call(2, 'Bash')]
  if (steer) log.push(human(3), call(4, 'Bash'))
  return turns(timeline(log), { live })[0]
}

function group(...entries: ReturnType<typeof event>[]): ProcessGroup {
  const [turn] = turns(timeline([human(0), ...entries]), { live: false })
  return turn.items[0] as ProcessGroup
}

describe('fold rules', () => {
  it('folds a finished turn, and opens it by default only in verbose', () => {
    const done = firstTurn(false)
    expect(canCollapseTurn(done)).toBe(true)
    expect(turnOpenByDefault(done, 'compact')).toBe(false)
    expect(turnOpenByDefault(done, 'standard')).toBe(false)
    expect(turnOpenByDefault(done, 'verbose')).toBe(true)
  })

  it('never folds a running, failed or steered turn', () => {
    const failed = turns(timeline([human(1), call(2, 'Bash')]), {
      failed: true,
      live: false,
    })[0]
    for (const turn of [firstTurn(true), failed, firstTurn(false, true)]) {
      expect(canCollapseTurn(turn)).toBe(false)
      expect(turnOpenByDefault(turn, 'compact')).toBe(true)
    }
  })

  it('opens only the live group of a running turn in standard', () => {
    const running = firstTurn(true)
    const live = running.items[0] as ProcessGroup
    expect(groupOpenByDefault(live, running, 'standard')).toBe(true)
    expect(groupOpenByDefault(live, running, 'compact')).toBe(false)
    const done = firstTurn(false)
    const old = done.items[0] as ProcessGroup
    expect(groupOpenByDefault(old, done, 'standard')).toBe(false)
    expect(groupOpenByDefault(old, done, 'verbose')).toBe(true)
  })

  it('keeps the live group open when a note follows it', () => {
    const [running] = turns(
      timeline([
        human(1),
        call(2, 'Bash'),
        event(3, 'state.changed', { from: 'queued', to: 'running' }),
      ]),
      { live: true },
    )
    const live = running.items[0] as ProcessGroup
    expect(running.items[1].kind).toBe('note')
    expect(groupOpenByDefault(live, running, 'standard')).toBe(true)
  })
})

describe('groupSummary', () => {
  it('counts calls by kind and failures', () => {
    expect(
      groupSummary(
        group(
          call(1, 'Bash'),
          call(2, 'Bash'),
          call(3, 'Bash', { is_error: true }),
          call(4, 'Read'),
          call(5, 'Read'),
        ),
      ),
    ).toBe('Ran 3 commands, read 2 files, 1 failed')
  })

  it('uses the singular for one call', () => {
    expect(groupSummary(group(call(1, 'Edit'), call(2, 'mcp__gh__pr')))).toBe(
      'Edited a file, made a call',
    )
  })

  it('says Thought for a group without calls', () => {
    expect(
      groupSummary(group(event(1, 'turn', { body: 'Hm.', kind: 'thinking' }))),
    ).toBe('Thought')
  })
})

describe('turnTitle', () => {
  it('names the state and the time', () => {
    expect(turnTitle(firstTurn(true))).toBe('Working…')
    expect(turnTitle(firstTurn(false))).toBe('Worked for 1s')
    expect(elapsed(124_000)).toBe('2m 4s')
    expect(elapsed(3_780_000)).toBe('1h 3m')
  })
})

describe('useConversationMode', () => {
  beforeEach(() => {
    const store = new Map<string, string>()
    vi.mocked(window.localStorage.getItem).mockImplementation(
      (key: string) => store.get(key) ?? null,
    )
    vi.mocked(window.localStorage.setItem).mockImplementation(
      (key: string, value: string) => {
        store.set(key, value)
      },
    )
  })

  it('defaults to standard and stores the choice', () => {
    const { result } = renderHook(() => useConversationMode())
    expect(result.current[0]).toBe('standard')
    act(() => result.current[1]('verbose'))
    expect(result.current[0]).toBe('verbose')
    expect(window.localStorage.getItem(MODE_KEY)).toBe('verbose')
    expect(renderHook(() => useConversationMode()).result.current[0]).toBe(
      'verbose',
    )
  })

  it('ignores an unknown stored value', () => {
    window.localStorage.setItem(MODE_KEY, 'loud')
    expect(renderHook(() => useConversationMode()).result.current[0]).toBe(
      'standard',
    )
  })
})

describe('useFoldState', () => {
  it('lets a click win over the default', () => {
    const { result } = renderHook(() => useFoldState())
    expect(result.current[0]('t:1', false)).toBe(false)
    act(() => result.current[1]('t:1', true))
    expect(result.current[0]('t:1', false)).toBe(true)
    expect(result.current[0]('t:2', true)).toBe(true)
  })
})
