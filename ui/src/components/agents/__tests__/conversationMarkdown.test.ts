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
    expect(md).toContain('*5s · 2 tools · 1 failed · 12k tokens*')
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

  it('falls back to the first description line', () => {
    expect(
      conversationMarkdown({ description: 'Do it\nnow', title: '' }, []),
    ).toBe('# Do it\n')
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
