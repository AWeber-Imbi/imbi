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
    expect(
      systemText(
        event(4, 'reopened', { outcome: 'done_acted', reason: 'Still broken' }),
      ),
    ).toBe('Reopened: Still broken')
  })

  it('words team and custom field changes', () => {
    expect(systemText(event(1, 'team.changed', { from: null, to: 't1' }))).toBe(
      'Team changed',
    )
    expect(systemText(event(2, 'team.changed', { from: 't1', to: null }))).toBe(
      'Team removed',
    )
    expect(
      systemText(
        event(3, 'custom_fields.changed', {
          from: { region: 'eu', severity: 'sev1' },
          to: { count: 2, region: 'eu', severity: 'sev2' },
        }),
      ),
    ).toBe('Custom fields changed: count, severity')
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
    for (const [reason, from, to, text] of [
      ['request_opened', 'running', 'blocked', 'Waiting for input'],
      ['session_opened', 'blocked', 'running', 'Resumed'],
      ['control_changed', 'running', 'paused', 'Paused'],
    ]) {
      expect(systemText(event(4, 'state.changed', { from, reason, to }))).toBe(
        text,
      )
    }
  })

  it('words the event types of a later release (ADR 0028)', () => {
    expect(
      [
        'ticket.created',
        'reopened',
        'assignee.changed',
        'parent.changed',
        'handed_off',
      ].map((type) => systemText(event(1, type))),
    ).toEqual([
      'Ticket created',
      'Reopened',
      'Assignee changed',
      'Parent changed',
      'Handed off',
    ])
    expect(
      systemText(
        event(2, 'request.resolved', {
          resolved_by: 'pat',
          status: 'withdrawn',
        }),
      ),
    ).toBe('Withdrawn by pat')
    expect(
      systemText(
        event(3, 'state.changed', { from: 'open', to: 'in_progress' }),
      ),
    ).toBe('In progress')
  })

  it('words a move of the parent', () => {
    expect(
      systemText(event(1, 'parent.changed', { from: null, to: 'T-2' })),
    ).toBe('Moved under T-2')
    expect(
      systemText(event(2, 'parent.changed', { from: 'T-2', to: null })),
    ).toBe('Moved from T-2 to the root')
  })

  it('turns an unknown event type into words', () => {
    expect(systemText(event(1, 'harness.egress_denied'))).toBe(
      'Harness egress denied',
    )
  })
})
