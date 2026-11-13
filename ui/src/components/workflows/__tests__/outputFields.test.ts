import { describe, expect, it } from 'vitest'

import {
  blankField,
  nameError,
  normalize,
  optionalCount,
  typeLabel,
} from '../outputFields'

describe('blankField', () => {
  it('takes the next free name, required, as a string', () => {
    expect(blankField([{ name: 'field_2', type: 'string' }])).toEqual({
      name: 'field_3',
      required: true,
      type: 'string',
    })
  })
})

describe('nameError', () => {
  it('reports a name that is not a key, or that a sibling has', () => {
    const fields = [
      { name: 'risk', type: 'string' as const },
      { name: 'risk', type: 'number' as const },
      { name: 'Bad name', type: 'string' as const },
    ]
    expect(nameError(fields[0], fields)).toBe('Another field has this name.')
    expect(nameError(fields[2], fields)).toMatch(/lower case letters/)
    expect(nameError(fields[0], [fields[0]])).toBeUndefined()
    const items = { name: 'items', type: 'string' as const }
    expect(nameError(items, [items])).toBe('This name is reserved.')
  })
})

describe('normalize', () => {
  it('gives an array string items and drops them when it stops being one', () => {
    const array = normalize({ name: 'tags', type: 'array' })
    expect(array).toEqual({ items: 'string', name: 'tags', type: 'array' })
    expect(normalize({ ...array, type: 'integer' })).toEqual({
      name: 'tags',
      type: 'integer',
    })
  })

  it('gives an object, or an array of objects, a first field', () => {
    expect(normalize({ name: 'owner', type: 'object' }).fields).toEqual([
      blankField([]),
    ])
    expect(
      normalize({ items: 'object', name: 'rows', type: 'array' }).fields,
    ).toHaveLength(1)
  })

  it('keeps enum and format only for string values', () => {
    const field = {
      enum: ['low', 'high'],
      format: null,
      name: 'risk',
      type: 'string' as const,
    }
    expect(normalize(field)).toEqual({
      enum: ['low', 'high'],
      name: 'risk',
      type: 'string',
    })
    expect(normalize({ ...field, items: 'string', type: 'array' })).toEqual({
      enum: ['low', 'high'],
      items: 'string',
      name: 'risk',
      type: 'array',
    })
    expect(normalize({ ...field, type: 'boolean' })).toEqual({
      name: 'risk',
      type: 'boolean',
    })
    expect(
      normalize({ ...field, enum: [], format: 'date', type: 'string' }),
    ).toEqual({ format: 'date', name: 'risk', type: 'string' })
  })
})

describe('optionalCount', () => {
  it('counts fields that are not required, at every level', () => {
    expect(
      optionalCount([
        { name: 'a', required: false, type: 'string' },
        {
          fields: [
            { name: 'b', required: false, type: 'string' },
            { name: 'c', type: 'string' },
          ],
          name: 'd',
          type: 'object',
        },
      ]),
    ).toBe(2)
  })
})

describe('typeLabel', () => {
  it('names arrays by their items and marks optional fields nullable', () => {
    expect(typeLabel({ items: 'object', name: 'rows', type: 'array' })).toBe(
      'array<object>',
    )
    expect(typeLabel({ name: 'risk', required: false, type: 'string' })).toBe(
      'string | null',
    )
    expect(typeLabel({ name: 'count', type: 'integer' })).toBe('integer')
  })
})
