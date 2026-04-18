import { describe, it, expect } from 'vitest'
import { applyJsonPatch } from '../json-patch'

describe('applyJsonPatch', () => {
  it('replaces a top-level key', () => {
    const out = applyJsonPatch({ name: 'old', description: 'keep' }, [
      { op: 'replace', path: '/name', value: 'new' },
    ])
    expect(out).toEqual({ name: 'new', description: 'keep' })
  })

  it('removes a top-level key', () => {
    const out = applyJsonPatch({ name: 'n', description: 'gone' }, [
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
      applyJsonPatch({}, [{ op: 'move', path: '/a', from: '/b' }]),
    ).toThrow(/unsupported/i)
  })

  it('throws on non-top-level path', () => {
    expect(() =>
      applyJsonPatch({}, [{ op: 'replace', path: '/a/b', value: 1 }]),
    ).toThrow(/top-level/i)
  })
})
