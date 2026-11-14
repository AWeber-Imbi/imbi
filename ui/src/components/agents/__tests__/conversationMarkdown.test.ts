import { describe, expect, it } from 'vitest'

import { conversationMarkdown, turnFooter } from '../conversationMarkdown'
import { turns } from '../conversationTurns'
import { timeline } from '../taskTimeline'
import { event } from './taskFixtures'

const human = (seq: number, body: string) =>
  event(seq, 'turn', { body }, { actor_id: 'dev', actor_kind: 'human' })
const bash = (seq: number, command: string, extra = {}) =>
  event(seq, 'tool.called', {
    arguments: { command },
    call_id: `c${seq}`,
    result: 'ok',
    tool: 'Bash',
    ...extra,
  })

const LOG = timeline([
  human(1, 'fix it\nplease'),
  event(2, 'turn', { body: 'Secret plan.', kind: 'thinking' }),
  bash(3, 'make test', { is_error: true }),
  bash(4, 'make test'),
  event(5, 'usage.reported', { tokens_in: 12000, tokens_out: 400 }),
  event(6, 'turn', { body: 'fixed' }),
  human(7, 'thanks'),
  event(8, 'turn', { body: 'Any time.' }),
])

describe('conversationMarkdown', () => {
  const md = conversationMarkdown(
    { title: 'Fix the build' },
    turns(LOG, { live: false }),
  )

  it('heads with the title and quotes the person', () => {
    expect(
      md.startsWith('# Fix the build\n\n## Turn 1\n\n> fix it\n> please'),
    ).toBe(true)
    expect(md).toContain('## Turn 2\n\n> thanks')
  })

  it('lists calls, marks failures, and keeps replies', () => {
    expect(md).toContain('- `Bash` make test — failed\n- `Bash` make test\n')
    expect(md).toContain('\n\nfixed\n\n')
    expect(md).not.toContain('Secret plan.')
  })

  it('ends each turn with its footer and the text with one newline', () => {
    expect(md).toContain('*5s · 2 tools · 1 failed · 12k uncached tokens*')
    expect(md.endsWith('Any time.\n\n*1s*\n')).toBe(true)
  })

  it('nests subagent calls under their call', () => {
    const out = conversationMarkdown(
      { title: 'T' },
      turns(
        timeline([
          human(1, 'go'),
          bash(2, 'ls', { parent_call_id: 'task-1' }),
          event(3, 'tool.called', {
            arguments: { description: 'look', subagent_type: 'search' },
            call_id: 'task-1',
            result: 'done',
            tool: 'Task',
          }),
        ]),
        { live: false },
      ),
    )
    expect(out).toContain('- `Subagent` search · look\n  - `Bash` ls')
  })

  it('says a pending subagent call is running only while it runs', () => {
    const log = timeline([
      human(1, 'go'),
      bash(2, 'ls', { parent_call_id: 't' }),
    ])
    const md = (live: boolean) =>
      conversationMarkdown({ title: 'T' }, turns(log, { live }))
    expect(md(true)).toContain('- `Subagent` running…\n  - `Bash` ls')
    expect(md(false)).toContain('- `Subagent` did not finish\n')
  })

  it('keeps a string argument as the call summary', () => {
    const out = conversationMarkdown(
      { title: 'T' },
      turns(
        timeline([
          human(1, 'go'),
          event(2, 'tool.called', {
            arguments: 'raw input',
            call_id: 'c2',
            result: 'ok',
            tool: 'mcp__x__y',
          }),
        ]),
        { live: false },
      ),
    )
    expect(out).toContain(' raw input\n')
    expect(out).not.toContain('{}')
  })

  it('quotes what a person answered to a request', () => {
    const out = conversationMarkdown(
      { title: 'T' },
      turns(
        timeline([
          human(1, 'go'),
          event(2, 'turn', { body: 'Which database?' }),
          event(
            3,
            'request.resolved',
            {
              answer: 'Staging',
              constraints: ['No writes'],
              kind: 'feedback',
              request_id: 'r1',
              resolved_by: 'dev',
              status: 'answered',
            },
            { actor_id: 'dev', actor_kind: 'human' },
          ),
        ]),
        { live: false },
      ),
    )
    expect(out).toContain('> Staging\n> - No writes')
  })

  it('falls back to the first description line', () => {
    expect(
      conversationMarkdown({ description: 'Do it\nnow', title: '' }, []),
    ).toBe('# Do it\n\n> Do it\n> now\n')
  })

  it('quotes what started the task before the first turn', () => {
    const out = conversationMarkdown(
      { description: 'Review the API\nand report', title: 'Review' },
      turns(timeline([bash(1, 'ls'), event(2, 'turn', { body: 'Done.' })]), {
        live: false,
      }),
    )
    expect(
      out.startsWith('# Review\n\n> Review the API\n> and report\n\n## Turn 1'),
    ).toBe(true)
  })

  it('does not repeat a request a person sent to open the task', () => {
    const out = conversationMarkdown(
      { description: 'fix it\nplease', title: 'T' },
      turns(LOG, { live: false }),
    )
    expect(out.split('> fix it').length).toBe(2)
  })
})

describe('turnFooter', () => {
  it('has no footer while the turn runs', () => {
    expect(turnFooter(turns(LOG, { live: true })[1])).toBe('1s')
    const running = turns(timeline([human(1, 'go'), bash(2, 'ls')]), {
      live: true,
    })[0]
    expect(turnFooter(running)).toBeNull()
  })
})
