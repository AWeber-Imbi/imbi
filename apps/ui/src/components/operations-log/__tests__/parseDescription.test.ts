import { describe, expect, it } from 'vitest'

import type { OperationsLogRecord } from '@/types'

import { parseDescription } from '../parseDescription'

function makeEntry(
  overrides: Partial<OperationsLogRecord> = {},
): OperationsLogRecord {
  return {
    description: '',
    entry_type: 'Configured',
    environment_slug: 'testing',
    id: 'opslog-1',
    occurred_at: '2026-05-12T02:24:59.841Z',
    plugin_slug: '',
    project_id: 'proj-1',
    project_slug: 'ai-content',
    recorded_at: '2026-05-12T02:24:59.841Z',
    recorded_by: 'alexs@aweber.com',
    ...overrides,
  }
}

describe('parseDescription', () => {
  it('returns text when plugin_slug is empty', () => {
    const result = parseDescription(
      makeEntry({ description: 'released v1.2.3 to testing' }),
    )
    expect(result).toEqual({ kind: 'text', text: 'released v1.2.3 to testing' })
  })

  it('returns text when description is not JSON', () => {
    const result = parseDescription(
      makeEntry({ description: 'plain text', plugin_slug: 'aws-ssm' }),
    )
    expect(result).toEqual({ kind: 'text', text: 'plain text' })
  })

  it('returns text when description is malformed JSON', () => {
    const result = parseDescription(
      makeEntry({ description: '{"oops"', plugin_slug: 'aws-ssm' }),
    )
    expect(result.kind).toBe('text')
  })

  it('returns text when JSON payload is an array', () => {
    const result = parseDescription(
      makeEntry({ description: '[1,2,3]', plugin_slug: 'aws-ssm' }),
    )
    expect(result.kind).toBe('text')
  })

  it('parses a valid plugin payload', () => {
    const raw =
      '{"action":"set_value","data_type":"string","key":"acm-pca-cacert-path","plugin_slug":"aws-ssm","secret":false}'
    const result = parseDescription(
      makeEntry({ description: raw, plugin_slug: 'aws-ssm' }),
    )
    expect(result).toEqual({
      action: 'set_value',
      kind: 'plugin',
      payload: {
        action: 'set_value',
        data_type: 'string',
        key: 'acm-pca-cacert-path',
        plugin_slug: 'aws-ssm',
        secret: false,
      },
      raw,
      summary: undefined,
    })
  })

  it('captures summary when present in the payload', () => {
    const raw = '{"summary":"Rotated production secret"}'
    const result = parseDescription(
      makeEntry({ description: raw, plugin_slug: 'aws-ssm' }),
    )
    expect(result).toMatchObject({
      kind: 'plugin',
      summary: 'Rotated production secret',
    })
  })

  it('treats non-string action values as missing', () => {
    const raw = '{"action":123}'
    const result = parseDescription(
      makeEntry({ description: raw, plugin_slug: 'aws-ssm' }),
    )
    expect(result).toMatchObject({ action: undefined, kind: 'plugin' })
  })

  it('handles whitespace before the JSON object', () => {
    const raw = '   {"action":"noop"}'
    const result = parseDescription(
      makeEntry({ description: raw, plugin_slug: 'aws-ssm' }),
    )
    expect(result).toMatchObject({ action: 'noop', kind: 'plugin' })
  })
})
