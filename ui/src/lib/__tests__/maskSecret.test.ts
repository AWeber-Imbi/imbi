import { describe, expect, it } from 'vitest'

import { containsCredentials, maskSecret } from '@/lib/maskSecret'

describe('containsCredentials', () => {
  it.each([
    ['postgres://user:pw@db', true],
    ['redis://:pw@cache', true],
    ['https://user:pa,ss@example.org', true],
    ['a, amqp://u:p@mq', true],
    ['https://api.example?token=t&contact=ops:team@example.org', false],
    ['https://example.org/path', false],
    ['plain', false],
  ])('%s -> %s', (value, expected) => {
    expect(containsCredentials(value)).toBe(expected)
  })
})

describe('maskSecret', () => {
  it('masks only the password of a URL', () => {
    expect(maskSecret('redis://:pw@cache')).toBe('redis://:••••••••@cache')
  })

  it('masks a password that contains @', () => {
    expect(maskSecret('postgres://user:pa@ss@db')).toBe(
      'postgres://user:••••••••@db',
    )
  })

  it('keeps an @ in the path visible', () => {
    expect(maskSecret('https://u:p@host/a@b')).toBe(
      'https://u:••••••••@host/a@b',
    )
  })

  it('masks a whole value when the userinfo would span a query', () => {
    expect(
      maskSecret('https://api.example?token=t&contact=ops:team@example.org'),
    ).not.toContain('token=t')
  })

  it('masks every part of a password that contains a comma', () => {
    expect(maskSecret('https://user:pa,ss@example.org')).not.toMatch(/pa|ss@/)
  })
})
