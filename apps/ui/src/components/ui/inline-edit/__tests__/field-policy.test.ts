import { describe, it, expect } from 'vitest'
import {
  isFieldEditable,
  pickInlineComponent,
  READ_ONLY_KEYS,
} from '../field-policy'

describe('isFieldEditable', () => {
  it('returns false for read-only keys', () => {
    expect(isFieldEditable('id', {})).toBe(false)
    expect(isFieldEditable('created_at', {})).toBe(false)
  })

  it('respects x-ui.editable=false', () => {
    expect(isFieldEditable('foo', { 'x-ui': { editable: false } })).toBe(false)
  })

  it('defaults to editable', () => {
    expect(isFieldEditable('foo', { type: 'string' })).toBe(true)
  })
})

describe('pickInlineComponent', () => {
  it('picks select for enum', () => {
    expect(pickInlineComponent({ enum: ['a', 'b'] })).toBe('select')
  })
  it('picks switch for boolean', () => {
    expect(pickInlineComponent({ type: 'boolean' })).toBe('switch')
  })
  it('picks date for date/date-time', () => {
    expect(pickInlineComponent({ format: 'date' })).toBe('date')
    expect(pickInlineComponent({ format: 'date-time' })).toBe('date')
  })
  it('picks number for integer/number', () => {
    expect(pickInlineComponent({ type: 'integer' })).toBe('number')
    expect(pickInlineComponent({ type: 'number' })).toBe('number')
  })
  it('picks text by default', () => {
    expect(pickInlineComponent({})).toBe('text')
  })
})

describe('READ_ONLY_KEYS', () => {
  it('includes id/created_at/updated_at', () => {
    expect(READ_ONLY_KEYS.has('id')).toBe(true)
    expect(READ_ONLY_KEYS.has('created_at')).toBe(true)
    expect(READ_ONLY_KEYS.has('updated_at')).toBe(true)
  })
})
