import { describe, expect, it } from 'vitest'

import { isIdOrReference, paramFields, paramSummary } from '../schemaFields'

describe('paramFields', () => {
  it('builds fields from a Pydantic schema, in schema order', () => {
    // The shape `model_json_schema()` gives for W1's step params.
    const fields = paramFields({
      $defs: {
        Recipient: {
          properties: {
            id: { title: 'Id', type: 'string' },
            kind: { enum: ['user', 'team'], title: 'Kind', type: 'string' },
          },
          type: 'object',
        },
      },
      properties: {
        branches: {
          items: { type: 'string' },
          title: 'Branches',
          type: 'array',
        },
        context: {
          anyOf: [{ type: 'string' }, { type: 'null' }],
          default: null,
          title: 'Context',
        },
        environment: { title: 'Environment', type: 'string' },
        min_confidence: {
          default: 0.7,
          title: 'Min Confidence',
          type: 'number',
        },
        model_id: {
          description: 'A decision model.',
          title: 'Model Id',
          type: 'string',
        },
        notify: { type: 'boolean' },
        target: {
          default: 'last_healthy',
          enum: ['last_healthy', 'previous'],
          title: 'Target',
          type: 'string',
        },
        to: {
          items: { $ref: '#/$defs/Recipient' },
          title: 'To',
          type: 'array',
        },
        version: {
          anyOf: [{ type: 'string' }, { type: 'null' }],
          title: 'Version',
        },
        webhook: { type: 'object' },
      },
      required: ['model_id'],
      type: 'object',
    })
    expect(fields).toEqual([
      { kind: 'list', label: 'Branches', name: 'branches', required: false },
      {
        kind: 'multiline',
        label: 'Context',
        mono: false,
        name: 'context',
        required: false,
      },
      {
        kind: 'source',
        label: 'Environment',
        name: 'environment',
        required: false,
        source: 'environment',
      },
      {
        kind: 'number',
        label: 'Min confidence',
        name: 'min_confidence',
        required: false,
      },
      {
        description: 'A decision model.',
        kind: 'source',
        label: 'Model',
        name: 'model_id',
        required: true,
        source: 'model',
      },
      { kind: 'boolean', label: 'Notify', name: 'notify', required: false },
      {
        kind: 'select',
        label: 'Target',
        name: 'target',
        options: [
          { label: 'Last healthy', value: 'last_healthy' },
          { label: 'Previous', value: 'previous' },
        ],
        required: false,
      },
      { kind: 'recipients', label: 'To', name: 'to', required: false },
      { kind: 'text', label: 'Version', name: 'version', required: false },
      { kind: 'json', label: 'Webhook', name: 'webhook', required: false },
    ])
  })
})

describe('paramSummary', () => {
  it('shows the first two values and skips ids', () => {
    expect(
      paramSummary({
        branches: ['Yes', 'No'],
        model_id: 'a1b2c3',
        prompt: 'Roll back?\nMore text',
        timeout: 'not shown',
      }),
    ).toBe('2 branches · Roll back?')
  })
})

describe('isIdOrReference', () => {
  it('takes a literal id or one plain reference only', () => {
    expect(isIdOrReference('')).toBe(true)
    expect(isIdOrReference('abc123')).toBe(true)
    expect(isIdOrReference('{{ trigger.user }}')).toBe(true)
    expect(isIdOrReference('{{ decide.choice.id }}')).toBe(true)
    expect(isIdOrReference('x{{ trigger.user }}')).toBe(false)
    expect(isIdOrReference('{{ trigger.user | lower }}')).toBe(false)
    expect(isIdOrReference("{{ 'abc' }}")).toBe(false)
    expect(isIdOrReference('{% if x %}a{% endif %}')).toBe(false)
  })
})
