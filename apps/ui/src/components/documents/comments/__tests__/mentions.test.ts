import { describe, expect, it } from 'vitest'

import {
  filterCandidates,
  insertMention,
  mentionQueryAt,
  parseBody,
  resolveMentions,
} from '../mentions'

const PEOPLE = [
  { display_name: 'Ada Lovelace', email: 'ada@example.com' },
  { display_name: 'Ada', email: 'ada2@example.com' },
  { display_name: 'Grace Hopper', email: 'grace@example.com' },
]

const NAMES = new Map(PEOPLE.map((p) => [p.email, p.display_name]))

describe('mentionQueryAt', () => {
  it('detects an @ query at the caret', () => {
    const v = 'hi @Gra'
    expect(mentionQueryAt(v, v.length)).toEqual({ start: 3, text: 'Gra' })
  })

  it('detects an empty query right after @', () => {
    const v = 'hi @'
    expect(mentionQueryAt(v, v.length)).toEqual({ start: 3, text: '' })
  })

  it('allows a single space inside a multi-word name query', () => {
    const v = '@Ada Lov'
    expect(mentionQueryAt(v, v.length)).toEqual({ start: 0, text: 'Ada Lov' })
  })

  it('does not trigger inside an email address', () => {
    const v = 'mail me at foo@bar'
    expect(mentionQueryAt(v, v.length)).toBeNull()
  })

  it('does not trigger when there is no @ before the caret', () => {
    const v = 'plain text'
    expect(mentionQueryAt(v, v.length)).toBeNull()
  })

  it('uses the caret position, not the end of the string', () => {
    const v = '@Ada more text'
    // caret right after "@Ada"
    expect(mentionQueryAt(v, 4)).toEqual({ start: 0, text: 'Ada' })
  })
})

describe('filterCandidates', () => {
  it('matches on display name, case-insensitively', () => {
    expect(filterCandidates(PEOPLE, 'gra').map((c) => c.email)).toEqual([
      'grace@example.com',
    ])
  })

  it('matches on email', () => {
    expect(filterCandidates(PEOPLE, 'ada2').map((c) => c.email)).toEqual([
      'ada2@example.com',
    ])
  })

  it('returns everything for an empty query', () => {
    expect(filterCandidates(PEOPLE, '')).toHaveLength(3)
  })
})

describe('insertMention', () => {
  it('replaces the query with @Name and a trailing space', () => {
    const v = 'hi @Gra'
    const q = mentionQueryAt(v, v.length)!
    const out = insertMention(v, q, v.length, 'Grace Hopper')
    expect(out.value).toBe('hi @Grace Hopper ')
    expect(out.caret).toBe(out.value.length)
  })

  it('keeps text that follows the caret', () => {
    const v = 'hi @Gra there'
    const q = mentionQueryAt(v, 7)!
    const out = insertMention(v, q, 7, 'Grace Hopper')
    expect(out.value).toBe('hi @Grace Hopper  there')
  })
})

describe('parseBody', () => {
  it('returns a single text segment when no names are known', () => {
    expect(parseBody('hi @Ada', new Map())).toEqual([
      { text: 'hi @Ada', type: 'text' },
    ])
  })

  it('styles a known mention and resolves its email', () => {
    const segs = parseBody('cc @Grace Hopper please', NAMES)
    expect(segs).toEqual([
      { text: 'cc ', type: 'text' },
      { email: 'grace@example.com', text: '@Grace Hopper', type: 'mention' },
      { text: ' please', type: 'text' },
    ])
  })

  it('prefers the longest matching name', () => {
    const segs = parseBody('@Ada Lovelace ok', NAMES)
    expect(segs[0]).toEqual({
      email: 'ada@example.com',
      text: '@Ada Lovelace',
      type: 'mention',
    })
  })

  it('leaves unknown @text as plain text', () => {
    expect(parseBody('@Nobody here', NAMES)).toEqual([
      { text: '@Nobody here', type: 'text' },
    ])
  })

  it('does not match a known name inside a longer word', () => {
    // "Ada" is known but "@Adam" is a different, unknown handle.
    expect(parseBody('@Adam said hi', NAMES)).toEqual([
      { text: '@Adam said hi', type: 'text' },
    ])
  })
})

describe('resolveMentions', () => {
  it('collects unique emails for every mentioned name', () => {
    const body = 'ping @Grace Hopper and @Ada'
    expect(resolveMentions(body, NAMES).sort()).toEqual([
      'ada2@example.com',
      'grace@example.com',
    ])
  })

  it('returns an empty array when nothing is mentioned', () => {
    expect(resolveMentions('no mentions here', NAMES)).toEqual([])
  })
})
