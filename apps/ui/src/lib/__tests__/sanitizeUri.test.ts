import { describe, expect, it } from 'vitest'

import { sanitizeHttpUrl, sanitizeUri } from '../utils'

describe('sanitizeUri', () => {
  it('accepts http(s) URLs', () => {
    expect(sanitizeUri('https://example.com/')).toBe('https://example.com/')
    expect(sanitizeUri('http://example.com')).toBe('http://example.com/')
  })

  it('accepts non-http URI schemes', () => {
    expect(sanitizeUri('postgresql://db.example.cloud/prod')).toBe(
      'postgresql://db.example.cloud/prod',
    )
    expect(sanitizeUri('ssh://host.example')).toBe('ssh://host.example')
    expect(sanitizeUri('mailto:ops@example.com')).toBe('mailto:ops@example.com')
  })

  it('rejects XSS-dangerous schemes', () => {
    expect(sanitizeUri('javascript:alert(1)')).toBeNull()
    expect(sanitizeUri('data:text/html,<script>')).toBeNull()
    expect(sanitizeUri('vbscript:msgbox')).toBeNull()
  })

  it('rejects empty and non-string input', () => {
    expect(sanitizeUri('')).toBeNull()
    expect(sanitizeUri(null)).toBeNull()
    expect(sanitizeUri(undefined)).toBeNull()
    expect(sanitizeUri(42)).toBeNull()
  })

  it('rejects unparseable values', () => {
    expect(sanitizeUri('not a url')).toBeNull()
  })
})

describe('sanitizeHttpUrl', () => {
  it('rejects non-http schemes', () => {
    expect(sanitizeHttpUrl('postgresql://db.example.cloud/prod')).toBeNull()
    expect(sanitizeHttpUrl('javascript:alert(1)')).toBeNull()
  })

  it('accepts http(s) URLs', () => {
    expect(sanitizeHttpUrl('https://example.com/')).toBe('https://example.com/')
  })
})
