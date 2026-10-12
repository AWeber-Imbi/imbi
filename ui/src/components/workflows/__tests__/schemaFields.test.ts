import { describe, expect, it } from 'vitest'

import { paramFields, paramSummary } from '../schemaFields'

describe('paramFields', () => {
  it('builds one field per property, in schema order', () => {
    const fields = paramFields({
      properties: {
        branches: { items: { type: 'string' }, type: 'array' },
        min_confidence: { title: 'Minimum confidence', type: 'number' },
        model_id: { type: 'string' },
        notify: { type: 'boolean' },
        prompt: { description: 'What to decide', type: 'string' },
        recipients: { type: 'object' },
        strategy: { enum: ['rolling', 'canary'], type: 'string' },
        subject: { type: ['string', 'null'] },
      },
      required: ['prompt'],
      type: 'object',
    })
    expect(fields).toEqual([
      { kind: 'list', label: 'Branches', name: 'branches', required: false },
      {
        kind: 'number',
        label: 'Minimum confidence',
        name: 'min_confidence',
        required: false,
      },
      {
        kind: 'source',
        label: 'Model',
        name: 'model_id',
        required: false,
        source: 'model',
      },
      { kind: 'boolean', label: 'Notify', name: 'notify', required: false },
      {
        description: 'What to decide',
        kind: 'multiline',
        label: 'Prompt',
        mono: false,
        name: 'prompt',
        required: true,
      },
      {
        kind: 'json',
        label: 'Recipients',
        name: 'recipients',
        required: false,
      },
      {
        kind: 'select',
        label: 'Strategy',
        name: 'strategy',
        options: ['rolling', 'canary'],
        required: false,
      },
      { kind: 'text', label: 'Subject', name: 'subject', required: false },
    ])
  })

  it('maps live-data parameters to their source', () => {
    const fields = paramFields({
      properties: {
        environment: { type: 'string' },
        project_id: { type: 'string' },
        webhook_id: { type: 'string' },
      },
    })
    expect(
      fields.map((f) => (f.kind === 'source' ? f.source : f.kind)),
    ).toEqual(['environment', 'project', 'webhook'])
  })
})

describe('paramSummary', () => {
  it('shows the first two values and skips ids', () => {
    expect(
      paramSummary({
        branches: ['Yes', 'No'],
        model_id: '0b7c6f5e-1d2a-4c3b-9e8f-7a6b5c4d3e2f',
        prompt: 'Roll back?\nMore text',
        timeout: 'not shown',
      }),
    ).toBe('2 branches · Roll back?')
  })
})
