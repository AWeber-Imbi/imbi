import { describe, expect, it } from 'vitest'

import { applyJsonPatch } from '../json-patch'

describe('applyJsonPatch', () => {
  it('replaces a top-level key', () => {
    const out = applyJsonPatch({ description: 'keep', name: 'old' }, [
      { op: 'replace', path: '/name', value: 'new' },
    ])
    expect(out).toEqual({ description: 'keep', name: 'new' })
  })

  it('adds a missing top-level key', () => {
    const out = applyJsonPatch({ name: 'n' }, [
      { op: 'add', path: '/events_published', value: true },
    ])
    expect(out).toEqual({ events_published: true, name: 'n' })
  })

  it('adds an existing top-level key (upsert)', () => {
    const out = applyJsonPatch({ description: 'old', name: 'n' }, [
      { op: 'add', path: '/description', value: 'new' },
    ])
    expect(out).toEqual({ description: 'new', name: 'n' })
  })

  it('removes a top-level key', () => {
    const out = applyJsonPatch({ description: 'gone', name: 'n' }, [
      { op: 'remove', path: '/description' },
    ])
    expect(out).toEqual({ name: 'n' })
  })

  it('returns a new object (does not mutate input)', () => {
    const input = { name: 'a' }
    const out = applyJsonPatch(input, [
      { op: 'replace', path: '/name', value: 'b' },
    ])
    expect(input).toEqual({ name: 'a' })
    expect(out).not.toBe(input)
  })

  it('throws on unsupported op', () => {
    expect(() =>
      applyJsonPatch({}, [{ from: '/b', op: 'move', path: '/a' }]),
    ).toThrow(/unsupported/i)
  })

  it('throws on non-top-level path', () => {
    expect(() =>
      applyJsonPatch({}, [{ op: 'replace', path: '/a/b', value: 1 }]),
    ).toThrow(/top-level/i)
  })
})
