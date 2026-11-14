import { describe, expect, it } from 'vitest'

import {
  entryKey,
  hashSeqOf,
  revealSeqOf,
  type Turn,
  turnForSeq,
  turns,
} from '../conversationTurns'
import { timeline } from '../taskTimeline'
import { event } from './taskFixtures'

const human = (seq: number, body: string) =>
  event(seq, 'turn', { body }, { actor_id: 'dev', actor_kind: 'human' })
const reply = (seq: number, body: string) => event(seq, 'turn', { body })
const thinking = (seq: number) =>
  event(seq, 'turn', { body: 'Hmm.', kind: 'thinking' })
const bash = (seq: number, extra: Record<string, unknown> = {}) =>
  event(seq, 'tool.called', {
    arguments: { command: 'ls' },
    call_id: `c${seq}`,
    result: 'ok',
    tool: 'Bash',
    ...extra,
  })

function shape(list: Turn[]) {
  return list.map((t) => ({
    items: t.items.map((i) =>
      i.kind === 'group' ? `group:${i.entries.length}` : i.kind,
    ),
    opening: t.opening.length,
    status: t.status,
    steered: t.steered,
  }))
}

describe('turns', () => {
  it('starts a turn at each human message after a reply', () => {
    const list = turns(
      timeline([
        human(1, 'Fix it.'),
        thinking(2),
        bash(3),
        reply(4, 'Fixed.'),
        human(5, 'Thanks, now test it.'),
        bash(6),
        reply(7, 'Tested.'),
      ]),
      { live: false },
    )
    expect(shape(list)).toEqual([
      {
        items: ['group:2', 'reply'],
        opening: 1,
        status: 'done',
        steered: false,
      },
      {
        items: ['group:1', 'reply'],
        opening: 1,
        status: 'done',
        steered: false,
      },
    ])
  })

  it('splits process groups at each reply', () => {
    const list = turns(
      timeline([
        human(1, 'Go.'),
        bash(2),
        reply(3, 'Halfway.'),
        bash(4),
        bash(5),
        reply(6, 'Done.'),
      ]),
      { live: false },
    )
    expect(shape(list)[0].items).toEqual([
      'group:1',
      'reply',
      'group:2',
      'reply',
    ])
  })

  it('keeps a human message during the work in the same turn as steering', () => {
    const list = turns(
      timeline([human(1, 'Go.'), bash(2), human(3, 'Use pytest.'), bash(4)]),
      { live: true },
    )
    expect(shape(list)).toEqual([
      {
        items: ['group:1', 'input', 'group:1'],
        opening: 1,
        status: 'running',
        steered: true,
      },
    ])
  })

  it('opens a turn with every human message before the first work', () => {
    const list = turns(
      timeline([human(1, 'Go.'), human(2, 'Also this.'), bash(3)]),
      { live: false },
    )
    expect(shape(list)[0]).toMatchObject({ opening: 2, steered: false })
  })

  it('counts usage tokens without showing usage', () => {
    const [turn] = turns(
      timeline([
        human(1, 'Go.'),
        bash(2),
        event(3, 'usage.reported', { tokens_in: 10, tokens_out: 5 }),
        event(4, 'usage.reported', { tokens_in: 1, tokens_out: 1 }),
        reply(5, 'Done.'),
      ]),
      { live: false },
    )
    expect(turn.stats.tokens).toBe(17)
    expect(shape([turn])[0].items).toEqual(['group:1', 'reply'])
  })

  it('marks the last turn running while the task works', () => {
    const log = [human(1, 'Go.'), reply(2, 'On it.'), bash(3)]
    expect(turns(timeline(log), { live: true }).at(-1)!.status).toBe('running')
    expect(turns(timeline(log), { live: false }).at(-1)!.status).toBe('done')
    expect(
      turns(timeline(log), { failed: true, live: false }).at(-1)!.status,
    ).toBe('failed')
  })

  it('is not running once the agent waits on a reply or a request', () => {
    const replied = turns(timeline([human(1, 'Go.'), reply(2, 'Done.')]), {
      live: true,
    })
    expect(replied[0].status).toBe('done')
    const asked = turns(
      timeline([
        human(1, 'Go.'),
        bash(2),
        event(3, 'request.opened', { request_id: 'r1', title: 'Apply?' }),
      ]),
      { live: true },
    )
    expect(asked[0].status).toBe('done')
  })

  it('leaves system notes out of the turn boundaries', () => {
    const list = turns(
      timeline([
        human(1, 'Go.'),
        reply(2, 'Done.'),
        event(3, 'outcome.set', { outcome: 'done_acted' }),
        human(4, 'One more.'),
        reply(5, 'Sure.'),
      ]),
      { live: true },
    )
    expect(shape(list)).toEqual([
      { items: ['reply', 'note'], opening: 1, status: 'done', steered: false },
      { items: ['reply'], opening: 1, status: 'done', steered: false },
    ])
  })

  it('counts subagent calls and their failures', () => {
    const [turn] = turns(
      timeline([
        human(1, 'Go.'),
        bash(2, { parent_call_id: 'task-1' }),
        bash(3, { is_error: true, parent_call_id: 'task-1' }),
        event(4, 'tool.called', {
          arguments: { subagent_type: 'search' },
          call_id: 'task-1',
          result: 'Found it.',
          tool: 'Task',
        }),
        reply(5, 'Done.'),
      ]),
      { live: false },
    )
    expect(turn.stats).toMatchObject({ errors: 1, tools: 3 })
    expect(turn.stats.durationMs).toBe(4000)
  })

  it('starts a turn without an opening when the log has no human message', () => {
    const list = turns(timeline([bash(1), reply(2, 'Done.')]), {
      live: false,
    })
    expect(shape(list)).toEqual([
      {
        items: ['group:1', 'reply'],
        opening: 0,
        status: 'done',
        steered: false,
      },
    ])
    expect(list[0].stats.durationMs).toBe(1000)
  })

  it('times a turn by its work, not the notes after it', () => {
    const [turn] = turns(
      timeline([
        human(1, 'Go.'),
        reply(3, 'Done.'),
        event(40, 'outcome.set', { outcome: 'done_acted' }),
      ]),
      { live: false },
    )
    expect(turn.stats.durationMs).toBe(2000)
  })

  it('has no duration for a turn with one event', () => {
    const [turn] = turns(timeline([human(1, 'Go.')]), { live: true })
    expect(turn.stats.durationMs).toBeNull()
    expect(turn.status).toBe('running')
  })

  it('puts the work sent after an answer back before its request', () => {
    const at = (time: string) => ({ at: `2026-10-08T${time}Z` })
    const list = turns(
      timeline([
        human(1, 'Go.'),
        bash(2),
        event(3, 'request.opened', { request_id: 'r1' }, at('12:00:04')),
        event(
          4,
          'request.resolved',
          { request_id: 'r1' },
          { ...at('13:00:00'), actor_id: 'dev', actor_kind: 'human' },
        ),
        event(5, 'turn', { body: 'Hmm.', kind: 'thinking' }, at('12:00:03')),
        event(6, 'turn', { body: 'Which one?' }, at('12:00:03')),
        event(7, 'tool.called', { call_id: 'c7', tool: 'ask' }, at('13:00:01')),
        event(8, 'turn', { body: 'Done.' }, at('13:00:30')),
      ]),
      { live: false },
    )
    expect(shape(list).map((t) => t.items)).toEqual([
      ['group:2', 'reply', 'input'],
      ['group:1', 'reply'],
    ])
    expect(list[1].stats.durationMs).toBe(30_000)
  })

  it('leaves the time a task waited to resume out of the turn', () => {
    const at = (time: string) => ({ at: `2026-10-08T${time}Z` })
    const list = turns(
      timeline([
        human(1, 'Go.'),
        reply(2, 'Done.'),
        human(3, 'Again, later.'),
        event(4, 'state.changed', { from: 'running', to: 'paused' }),
        event(
          5,
          'state.changed',
          { from: 'paused', to: 'queued' },
          at('14:00:00'),
        ),
        event(
          6,
          'state.changed',
          { from: 'queued', to: 'running' },
          at('14:00:05'),
        ),
        event(
          7,
          'tool.called',
          { call_id: 'c7', tool: 'Bash' },
          at('14:00:06'),
        ),
        event(8, 'turn', { body: 'Done again.' }, at('14:00:10')),
      ]),
      { live: false },
    )
    expect(list[1].stats.durationMs).toBe(5000)
  })

  it('puts delayed work inside a work group in time order', () => {
    const at = (time: string) => ({ at: `2026-10-08T${time}Z` })
    const list = turns(
      timeline([
        human(1, 'Go.'),
        bash(2),
        bash(5),
        event(6, 'request.opened', { request_id: 'r1' }),
        event(
          7,
          'request.resolved',
          { request_id: 'r1' },
          { ...at('13:00:00'), actor_id: 'dev', actor_kind: 'human' },
        ),
        event(
          8,
          'tool.called',
          { call_id: 'c8', tool: 'Read' },
          at('12:00:03'),
        ),
        event(9, 'turn', { body: 'Noted.' }, at('12:00:04')),
        event(10, 'turn', { body: 'Done.' }, at('13:00:30')),
      ]),
      { live: false },
    )
    const [first] = list
    expect(shape(list).map((t) => t.items)).toEqual([
      ['group:2', 'reply', 'group:1', 'input'],
      ['reply'],
    ])
    const groups = first.items.filter((i) => i.kind === 'group')
    expect(groups.map((g) => g.entries.map((e) => e.event!.seq))).toEqual([
      [2, 8],
      [5],
    ])
    expect(groups[0].id).toBe(`g:${entryKey(groups[0].entries[0])}`)
    expect(groups[1].id).toBe(`g:${entryKey(groups[1].entries[0])}`)
  })

  it('puts a running call stamped before the answer back before its request', () => {
    const at = (time: string) => ({ at: `2026-10-08T${time}Z` })
    const list = turns(
      timeline([
        human(1, 'Go.'),
        bash(2),
        event(3, 'request.opened', { request_id: 'r1' }, at('12:00:06')),
        event(
          4,
          'request.resolved',
          { request_id: 'r1' },
          { ...at('13:00:00'), actor_id: 'dev', actor_kind: 'human' },
        ),
        bash(5, { parent_call_id: 'task-9' }),
        event(6, 'turn', { body: 'Done.' }, at('13:00:30')),
      ]),
      { live: false },
    )
    expect(shape(list).map((t) => t.items)).toEqual([
      ['group:2', 'input'],
      ['reply'],
    ])
  })

  it('puts a finished call stamped before the answer back before its request', () => {
    const at = (time: string) => ({ at: `2026-10-08T${time}Z` })
    const list = turns(
      timeline([
        human(1, 'Go.'),
        bash(2),
        event(3, 'request.opened', { request_id: 'r1' }, at('12:00:06')),
        event(
          4,
          'request.resolved',
          { request_id: 'r1' },
          { ...at('13:00:00'), actor_id: 'dev', actor_kind: 'human' },
        ),
        bash(5, { parent_call_id: 'task-9' }),
        event(
          6,
          'tool.called',
          { call_id: 'task-9', result: 'Done.', tool: 'Task' },
          at('13:00:20'),
        ),
        event(7, 'turn', { body: 'Done.' }, at('13:00:30')),
      ]),
      { live: false },
    )
    expect(shape(list).map((t) => t.items)).toEqual([
      ['group:2', 'input'],
      ['reply'],
    ])
  })

  it('stops a turn at the next opening when a subagent works past it', () => {
    const at = (time: string) => ({ at: `2026-10-08T${time}Z` })
    const list = turns(
      timeline([
        human(1, 'Go.'),
        bash(2, { parent_call_id: 'task-1' }),
        event(3, 'request.opened', { request_id: 'r1' }),
        event(
          4,
          'request.resolved',
          { request_id: 'r1' },
          { ...at('13:00:00'), actor_id: 'dev', actor_kind: 'human' },
        ),
        event(
          5,
          'tool.called',
          { call_id: 'c5', parent_call_id: 'task-1', tool: 'Bash' },
          at('13:00:05'),
        ),
        event(
          6,
          'tool.called',
          { call_id: 'task-1', result: 'Done.', tool: 'Task' },
          at('13:00:10'),
        ),
        event(7, 'turn', { body: 'Done.' }, at('13:00:20')),
      ]),
      { live: false },
    )
    expect(list.map((t) => t.stats.durationMs)).toEqual([2000, 20_000])
  })

  it('times a turn from its first opening message', () => {
    const at = (time: string) => ({ at: `2026-10-08T${time}Z` })
    const [turn] = turns(
      timeline([
        human(1, 'Go.'),
        event(
          2,
          'turn',
          { body: 'Also check X.' },
          { ...at('12:00:10'), actor_id: 'dev', actor_kind: 'human' },
        ),
        event(
          3,
          'tool.called',
          { call_id: 'c3', tool: 'Bash' },
          at('12:00:05'),
        ),
        event(4, 'turn', { body: 'Done.' }, at('12:00:20')),
      ]),
      { live: false },
    )
    expect(turn.opening).toHaveLength(2)
    expect(turn.stats.durationMs).toBe(19_000)
  })
})

describe('turnForSeq', () => {
  const list = turns(
    timeline([
      human(1, 'Look around.'),
      bash(2, { parent_call_id: 'task-1' }),
      event(3, 'usage.reported', { tokens_in: 5, tokens_out: 1 }),
      event(4, 'tool.called', {
        arguments: { subagent_type: 'search' },
        call_id: 'task-1',
        result: 'Found it.',
        tool: 'Task',
      }),
      reply(5, 'Found it.'),
      human(6, 'Now fix it.'),
      bash(7),
      event(8, 'usage.reported', { tokens_in: 9, tokens_out: 2 }),
      reply(9, 'Fixed.'),
    ]),
    { live: false },
  )

  it('finds the turn and the work group that hold an event', () => {
    expect(turnForSeq(list, 7)).toEqual({
      calls: [],
      group: list[1].items[0].id,
      turn: list[1],
    })
    expect(turnForSeq(list, 6)).toEqual({
      calls: [],
      group: null,
      turn: list[1],
    })
    expect(turnForSeq(list, 5)).toEqual({
      calls: [],
      group: null,
      turn: list[0],
    })
  })

  it('shows a subagent event in the turn of its Agent call', () => {
    const group = list[0].items[0]
    const call =
      group.kind === 'group'
        ? group.entries.find((e) => e.children.length)
        : undefined
    expect(call).toBeDefined()
    expect(turnForSeq(list, 2)).toEqual({
      calls: [call && entryKey(call)],
      group: list[0].items[0].id,
      turn: list[0],
    })
  })

  it('finds an Agent call by its own seq, after its subagent events', () => {
    expect(turnForSeq(list, 4)).toEqual({
      calls: [],
      group: list[0].items[0].id,
      turn: list[0],
    })
  })

  it('puts an event the conversation leaves out in the turn before it', () => {
    expect(turnForSeq(list, 8)?.turn).toBe(list[1])
    expect(turnForSeq(list, 3)?.turn).toBe(list[0])
  })

  it('puts an event from before every turn in the first turn', () => {
    expect(turnForSeq(list, 0)).toEqual({
      calls: [],
      group: null,
      turn: list[0],
    })
  })

  it('finds nothing without a turn', () => {
    expect(turnForSeq([], 1)).toBeNull()
  })

  it('opens a running Agent call to show its first subagent event', () => {
    const running = turns(
      timeline([
        human(1, 'Look around.'),
        bash(2, { parent_call_id: 'task-1' }),
        bash(3, { parent_call_id: 'task-1' }),
      ]),
      { live: true },
    )
    expect(turnForSeq(running, 2)?.calls).toEqual(['call:task-1'])
    expect(turnForSeq(running, 3)?.calls).toEqual(['call:task-1'])
  })

  it('reads the seq of an event permalink', () => {
    expect(hashSeqOf('#e42')).toBe(42)
    expect(hashSeqOf('#top')).toBeNull()
    expect(hashSeqOf('')).toBeNull()
  })
})

describe('revealSeqOf', () => {
  it('reads a numeric seq from the router state', () => {
    expect(revealSeqOf({ revealSeq: 4 })).toBe(4)
    expect(revealSeqOf({ revealSeq: '4' })).toBeNull()
    expect(revealSeqOf(null)).toBeNull()
    expect(revealSeqOf('x')).toBeNull()
  })
})
