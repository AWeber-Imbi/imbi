import { describe, expect, it } from 'vitest'

import { systemText } from '../taskText'
import { event } from './taskFixtures'

describe('systemText', () => {
  it('words task events in plain language', () => {
    expect(systemText(event(1, 'session.opened'))).toBe('Session opened')
    expect(
      systemText(event(2, 'project.associated', { project_slug: 'lists' })),
    ).toBe('Linked to project lists')
    expect(
      systemText(
        event(3, 'dependency.added', {
          dependent_short_id: 'T-2',
          prerequisite_short_id: 'T-1',
        }),
      ),
    ).toBe('Dependency added: T-2 waits on T-1')
  })

  it('says why a task stopped running unless the reason is routine', () => {
    expect(
      systemText(
        event(1, 'state.changed', {
          from: 'running',
          reason: 'runner_lost',
          to: 'queued',
        }),
      ),
    ).toBe('Queued: runner lost')
    expect(
      systemText(
        event(2, 'state.changed', {
          from: 'blocked',
          reason: 'request_resolved',
          to: 'running',
        }),
      ),
    ).toBe('Resumed')
    expect(
      systemText(
        event(3, 'state.changed', {
          from: 'running',
          reason: 'session_closed',
          to: 'paused',
        }),
      ),
    ).toBe('Paused')
  })

  it('turns an unknown event type into words', () => {
    expect(systemText(event(1, 'harness.egress_denied'))).toBe(
      'Harness egress denied',
    )
  })
})
