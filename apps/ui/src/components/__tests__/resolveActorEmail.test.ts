import { describe, expect, it } from 'vitest'

import { resolveActorEmail } from '../ProjectsView'

describe('resolveActorEmail', () => {
  const loginToEmail = new Map([['edl', 'edl@example.com']])

  it('maps a bare login to the matching Imbi user email', () => {
    expect(resolveActorEmail('edl', loginToEmail)).toBe('edl@example.com')
  })

  it('passes an email through unchanged', () => {
    expect(resolveActorEmail('someone@example.com', loginToEmail)).toBe(
      'someone@example.com',
    )
  })

  it('returns undefined for an unmatched login', () => {
    expect(resolveActorEmail('Ed Long', loginToEmail)).toBeUndefined()
    expect(resolveActorEmail('ghost', loginToEmail)).toBeUndefined()
  })

  it('returns undefined for null/empty actors', () => {
    expect(resolveActorEmail(null, loginToEmail)).toBeUndefined()
    expect(resolveActorEmail(undefined, loginToEmail)).toBeUndefined()
    expect(resolveActorEmail('', loginToEmail)).toBeUndefined()
  })
})
