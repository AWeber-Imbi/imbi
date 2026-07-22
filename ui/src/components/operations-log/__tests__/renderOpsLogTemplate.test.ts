import { describe, expect, it } from 'vitest'

import type { OperationsLogRecord } from '@/types'

import {
  renderOpsLogLabel,
  renderOpsLogTemplate,
} from '../renderOpsLogTemplate'

function makeEntry(
  overrides: Partial<OperationsLogRecord> = {},
): OperationsLogRecord {
  return {
    description: '',
    entry_type: 'Configured',
    environment_slug: 'testing',
    id: 'opslog-1',
    occurred_at: '2026-05-12T02:24:59.841Z',
    plugin_slug: 'aws-ssm',
    project_id: 'proj-1',
    project_slug: 'ai-content',
    recorded_at: '2026-05-12T02:24:59.841Z',
    recorded_by: 'alexs@aweber.com',
    ...overrides,
  }
}

describe('renderOpsLogTemplate', () => {
  it('returns the template unchanged when there are no placeholders', () => {
    const result = renderOpsLogTemplate('configured the database', {
      entry: makeEntry(),
      payload: {},
    })
    expect(result).toBe('configured the database')
  })

  it('substitutes payload values first', () => {
    const result = renderOpsLogTemplate('set {{key}}', {
      entry: makeEntry(),
      payload: { key: 'DATABASE_URL' },
    })
    expect(result).toBe('set DATABASE_URL')
  })

  it('falls back to display values when key is not in payload', () => {
    const result = renderOpsLogTemplate('deployed to {{environment}}', {
      display: { environment: 'Production' },
      entry: makeEntry({ environment_slug: 'production' }),
      payload: {},
    })
    expect(result).toBe('deployed to Production')
  })

  it('falls back to entry fields when key is in neither payload nor display', () => {
    const result = renderOpsLogTemplate('rolled out {{version}}', {
      entry: makeEntry({ version: 'v1.2.3' } as never),
      payload: {},
    })
    expect(result).toBe('rolled out v1.2.3')
  })

  it('renders empty string for missing keys', () => {
    const result = renderOpsLogTemplate('hello {{missing}} there', {
      entry: makeEntry(),
      payload: {},
    })
    expect(result).toBe('hello  there')
  })

  it('handles multiple placeholders in one template', () => {
    const result = renderOpsLogTemplate(
      '{{performer}} promoted {{project}} to {{environment}}',
      {
        display: {
          environment: 'Staging',
          performer: 'alexs',
          project: 'ai-content',
        },
        entry: makeEntry(),
        payload: {},
      },
    )
    expect(result).toBe('alexs promoted ai-content to Staging')
  })

  it('treats null/undefined payload values as empty strings', () => {
    expect(
      renderOpsLogTemplate('value={{key}}', {
        entry: makeEntry(),
        payload: { key: null },
      }),
    ).toBe('value=')
    expect(
      renderOpsLogTemplate('value={{key}}', {
        entry: makeEntry(),
        payload: { key: undefined },
      }),
    ).toBe('value=')
  })

  it('coerces non-string payload values to strings', () => {
    expect(
      renderOpsLogTemplate('count={{n}} flag={{b}}', {
        entry: makeEntry(),
        payload: { b: true, n: 42 },
      }),
    ).toBe('count=42 flag=true')
  })

  it('payload key takes precedence over display and entry', () => {
    const result = renderOpsLogTemplate('{{environment}}', {
      display: { environment: 'DisplayEnv' },
      entry: makeEntry({ environment_slug: 'EntryEnv' }),
      payload: { environment: 'PayloadEnv' },
    })
    expect(result).toBe('PayloadEnv')
  })

  it('display key takes precedence over entry', () => {
    const result = renderOpsLogTemplate('{{environment}}', {
      display: { environment: 'DisplayEnv' },
      entry: makeEntry({ environment_slug: 'EntryEnv' }),
      payload: {},
    })
    expect(result).toBe('DisplayEnv')
  })

  it('tolerates whitespace around placeholder names', () => {
    const result = renderOpsLogTemplate('value={{  key  }}', {
      entry: makeEntry(),
      payload: { key: 'hello' },
    })
    expect(result).toBe('value=hello')
  })

  it('does not match placeholders that contain dots', () => {
    // The renderer's placeholder regex matches ``\w+`` only. Dotted
    // names are left untouched so plugins flatten nested payloads
    // before sending rather than relying on path-style traversal.
    const result = renderOpsLogTemplate('{{nested.key}}', {
      entry: makeEntry(),
      payload: { 'nested.key': 'value' },
    })
    expect(result).toBe('{{nested.key}}')
  })
})

describe('renderOpsLogLabel', () => {
  it('renders the template label field', () => {
    const result = renderOpsLogLabel(
      { label: 'set {{key}}', summary: 'set value' },
      {
        entry: makeEntry(),
        payload: { key: 'DATABASE_URL' },
      },
    )
    expect(result).toBe('set DATABASE_URL')
  })
})
