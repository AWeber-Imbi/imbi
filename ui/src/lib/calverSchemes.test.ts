import { describe, expect, it } from 'vitest'

import { schemeError, schemePattern } from './calverSchemes'
import { fullMatch } from './versionFormats'

describe('schemePattern', () => {
  it('builds the same pattern text as the API', () => {
    // From calver_scheme_pattern('YY.0M[.MICRO]') in imbi.common.versioning.
    expect(schemePattern('YY.0M[.MICRO]')).toBe(
      '^(?P<t0>0|[1-9]\\d{0,2})\\.(?P<t1>1[0-2]|0[1-9])(?:\\.(?P<t2>0|[1-9]\\d*))?$',
    )
  })

  it.each([
    ['YY.0M.MICRO', '26.04.1', true],
    ['YY.0M.MICRO', '26.4.1', false],
    ['YYYY.0M.0D', '2026.13.01', false],
    ['YYYY-0M-0D[.MODIFIER]', '2026-09-30.acacia', true],
    ['YYYY.M.D_MICRO', '2026.9.17_1', true],
  ])('%s matches %s: %s', (scheme, tag, expected) => {
    expect(fullMatch(schemePattern(scheme), tag)).toBe(expected)
  })
})

describe('schemeError', () => {
  it('is null for a valid scheme', () => {
    expect(schemeError('YYYY.0M.0D[.MICRO]')).toBeNull()
  })

  it.each([
    ['YYYY.QQ', 'Unknown calver token QQ'],
    ['0M.MICRO', 'A calver scheme needs one year: YYYY, YY, or 0Y'],
    ['YYYY.0W.D', 'Weeks cannot be combined with months or days'],
    [
      'YYYY.0M.MODIFIER',
      'MODIFIER must be the optional last segment, e.g. [-MODIFIER]',
    ],
  ])('explains %s', (scheme, message) => {
    expect(schemeError(scheme)).toBe(message)
  })
})
