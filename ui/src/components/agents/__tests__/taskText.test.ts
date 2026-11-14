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

  it('turns an unknown event type into words', () => {
    expect(systemText(event(1, 'harness.egress_denied'))).toBe(
      'Harness egress denied',
    )
  })
})
