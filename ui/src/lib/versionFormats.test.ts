import { describe, expect, it } from 'vitest'

import {
  buildRows,
  isTagAllowed,
  tagFormatHint,
  toFormats,
} from './versionFormats'

const CALVER = '^\\d{4}([.-])\\d{1,2}\\1\\d{1,2}(?:[.-]\\w+)?$'

describe('isTagAllowed', () => {
  it('requires semver when no policy is configured', () => {
    expect(isTagAllowed('v1.2.3', [])).toBe(true)
    expect(isTagAllowed('2026.09.17-0', [])).toBe(false)
  })

  it('accepts any configured pattern, built-in or custom', () => {
    const formats = [
      { label: 'Calendar versioning', pattern: CALVER },
      { label: 'Ticket', pattern: '^REL-\\d+$' },
    ]
    expect(isTagAllowed('2026.09.17-0', formats)).toBe(true)
    expect(isTagAllowed('REL-42', formats)).toBe(true)
    expect(isTagAllowed('v1.2.3', formats)).toBe(false)
  })

  it('evaluates Python named groups saved through the API', () => {
    const formats = [{ label: 'Kind', pattern: '^(?P<k>nightly|rc)-(?P=k)$' }]
    expect(isTagAllowed('nightly-nightly', formats)).toBe(true)
    expect(isTagAllowed('nightly-rc', formats)).toBe(false)
  })

  it('leaves a pattern this engine cannot compile to the server', () => {
    expect(isTagAllowed('anything', [{ label: 'Odd', pattern: '(?i)x' }])).toBe(
      true,
    )
  })
})

describe('tagFormatHint', () => {
  it('names the allowed formats with built-in examples', () => {
    expect(
      tagFormatHint([
        { label: 'Calendar versioning', pattern: CALVER },
        { label: 'Ticket', pattern: '^REL-\\d+$' },
      ]),
    ).toBe('Use a Calendar versioning or Ticket tag, e.g. 2026.09.17-0')
    expect(tagFormatHint([])).toBe('Use a semver tag, e.g. v6.5.2')
  })
})

describe('buildRows', () => {
  it('renders the previous calver pattern as the built-in row', () => {
    const rows = buildRows([
      {
        label: 'Calendar versioning',
        pattern: '^\\d{4}\\.\\d{1,2}(?:\\.\\d{1,2})?$',
      },
    ])
    const calver = rows.find((r) => r.label === 'Calendar versioning')
    expect(calver?.builtin).toBe(true)
    expect(calver?.enabled).toBe(true)
    expect(rows.filter((r) => !r.builtin)).toHaveLength(0)
    expect(toFormats(rows)).toEqual([
      { label: 'Calendar versioning', pattern: CALVER },
    ])
  })
})
