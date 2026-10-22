import { describe, expect, it } from 'vitest'

import {
  buildRows,
  hasLegacySemverPattern,
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
  it('keeps the previous calver pattern as stored', () => {
    const legacy = {
      label: 'Calendar versioning',
      pattern: '^\\d{4}\\.\\d{1,2}(?:\\.\\d{1,2})?$',
    }
    const formats = [{ label: 'Ticket', pattern: '^REL-\\d+$' }, legacy]
    const rows = buildRows(formats)
    expect(
      rows.find((r) => r.builtin && r.label === 'Calendar versioning')?.enabled,
    ).toBe(false)
    const custom = rows.find((r) => r.pattern === legacy.pattern)
    expect(custom?.builtin).toBe(false)
    expect(custom?.description).toContain('2026.09')
    // An edit to another row does not change the stored calver pattern.
    const edited = rows.map((r) =>
      r.label === 'Ticket' ? { ...r, pattern: '^REL-\\d{3}$' } : r,
    )
    expect(toFormats(edited)).toEqual([
      { label: 'Ticket', pattern: '^REL-\\d{3}$' },
      legacy,
    ])
  })
})

describe('Semantic versioning built-in', () => {
  it('accepts a leading v like the backend', () => {
    const row = buildRows([]).find((r) => r.label === 'Semantic versioning')!
    const formats = [{ label: row.label, pattern: row.pattern }]
    expect(isTagAllowed('v1.2.3', formats)).toBe(true)
    expect(isTagAllowed('1.2.3', formats)).toBe(true)
    expect(isTagAllowed('V1.2.3', formats)).toBe(false)
  })

  it('renders the previous pattern as the built-in row', () => {
    const rows = buildRows([
      {
        label: 'Semantic versioning',
        pattern:
          '^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-([0-9A-Za-z-.]+))?(?:\\+([0-9A-Za-z-.]+))?$',
      },
    ])
    expect(rows.filter((r) => !r.builtin)).toHaveLength(0)
    expect(toFormats(rows)[0].pattern.startsWith('^v?')).toBe(true)
  })

  it('detects a stored previous pattern', () => {
    const legacy = {
      label: 'Semantic versioning',
      pattern:
        '^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)(?:-([0-9A-Za-z-.]+))?(?:\\+([0-9A-Za-z-.]+))?$',
    }
    expect(hasLegacySemverPattern([legacy])).toBe(true)
    expect(hasLegacySemverPattern(toFormats(buildRows([legacy])))).toBe(false)
  })

  it('does not flag the previous calendar pattern', () => {
    expect(
      hasLegacySemverPattern([
        {
          label: 'Calendar versioning',
          pattern: '^\\d{4}\\.\\d{1,2}(?:\\.\\d{1,2})?$',
        },
      ]),
    ).toBe(false)
  })
})
