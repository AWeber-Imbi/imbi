import { describe, expect, it } from 'vitest'

import { type Turn, turns } from '../conversationTurns'
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
})
