import { describe, expect, it } from 'vitest'

import { isIdOrReference, paramFields, paramSummary } from '../schemaFields'
import { CONDITION, SCRIPT } from './fixtures'

describe('paramFields for the script step', () => {
  it('edits code as plain text and inputs as name and value rows', () => {
    expect(
      paramFields(SCRIPT.params_schema, SCRIPT.raw_params).map((f) => [
        f.name,
        f.kind,
      ]),
    ).toEqual([
      ['branches', 'list'],
      ['code', 'code'],
      ['inputs', 'inputs'],
      ['output_fields', 'outputFields'],
    ])
  })

  it('edits any free-form map as name and value rows', () => {
    const [field] = paramFields({
      properties: {
        custom_fields: { additionalProperties: true, type: 'object' },
      },
      type: 'object',
    })
    expect(field?.kind).toBe('inputs')
  })

  it('treats a param as code only when the step type names it raw', () => {
    const [field] = paramFields(SCRIPT.params_schema).filter(
      (f) => f.name === 'code',
    )
    expect(field?.kind).toBe('text')
  })

  it('edits a list of manual trigger inputs as name and type rows', () => {
    const [field] = paramFields({
      $defs: {
        ManualInput: {
          properties: {
            name: { type: 'string' },
            type: { enum: ['string', 'number', 'boolean'], type: 'string' },
          },
          type: 'object',
        },
      },
      properties: {
        inputs: { items: { $ref: '#/$defs/ManualInput' }, type: 'array' },
      },
      type: 'object',
    })
    expect(field).toMatchObject({
      kind: 'manualInputs',
      options: [
        { label: 'String', value: 'string' },
        { label: 'Number', value: 'number' },
        { label: 'Boolean', value: 'boolean' },
      ],
    })
  })
})

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

describe('paramFields for the release step', () => {
  it('picks both environments and takes the notes as markdown', () => {
    const fields = paramFields({
      properties: {
        environment: { type: 'string' },
        from_environment: { type: 'string' },
        release_notes: { default: '', type: 'string' },
      },
      type: 'object',
    })
    expect(fields.map((f) => [f.name, f.kind])).toEqual([
      ['environment', 'source'],
      ['from_environment', 'source'],
      ['release_notes', 'multiline'],
    ])
  })
})

describe('paramFields for the agent step', () => {
  it('picks the agent from live data and takes a long instruction', () => {
    const fields = paramFields({
      properties: {
        agent_id: { title: 'Agent Id', type: 'string' },
        budget: {
          anyOf: [{ minimum: 0, type: 'number' }, { type: 'null' }],
          default: null,
        },
        instruction: { title: 'Instruction', type: 'string' },
        output_fields: {
          items: { $ref: '#/$defs/OutputField' },
          type: 'array',
        },
      },
      required: ['agent_id', 'instruction'],
      type: 'object',
    })
    expect(fields).toEqual([
      {
        kind: 'source',
        label: 'Agent',
        name: 'agent_id',
        required: true,
        source: 'agent',
      },
      { kind: 'number', label: 'Budget', name: 'budget', required: false },
      {
        kind: 'multiline',
        label: 'Instruction',
        mono: false,
        name: 'instruction',
        required: true,
      },
      {
        kind: 'outputFields',
        label: 'Output fields',
        name: 'output_fields',
        required: false,
      },
    ])
  })
})

describe('paramFields for the slack step', () => {
  it('takes a channel ID with a hint and the text as a template', () => {
    const hint =
      'Channel ID, for example C0123456789. Invite the Imbi bot to the channel first.'
    expect(
      paramFields({
        properties: {
          channel: { description: hint, title: 'Channel', type: 'string' },
          text: { title: 'Text', type: 'string' },
        },
        required: ['channel', 'text'],
        type: 'object',
      }),
    ).toEqual([
      {
        description: hint,
        kind: 'text',
        label: 'Channel',
        name: 'channel',
        required: true,
      },
      {
        kind: 'multiline',
        label: 'Text',
        mono: false,
        name: 'text',
        required: true,
      },
    ])
  })

  it('takes an optional ticket as a text field', () => {
    expect(
      paramFields({
        properties: {
          ticket: {
            anyOf: [{ type: 'string' }, { type: 'null' }],
            default: null,
            title: 'Ticket',
          },
        },
        type: 'object',
      }),
    ).toEqual([
      { kind: 'text', label: 'Ticket', name: 'ticket', required: false },
    ])
  })
})

describe('paramFields for the condition step', () => {
  it('builds condition rows with readable operators', () => {
    expect(paramFields(CONDITION.params_schema)).toEqual([
      {
        kind: 'conditions',
        label: 'Conditions',
        name: 'conditions',
        options: [
          { label: 'equals', value: 'equals' },
          { label: 'is greater than', value: 'greater_than' },
          { label: 'is empty', value: 'is_empty' },
        ],
        required: true,
      },
      {
        kind: 'boolean',
        label: 'Ignore case',
        name: 'ignore_case',
        required: false,
      },
      {
        kind: 'select',
        label: 'Match',
        name: 'match',
        options: [
          { label: 'All', value: 'all' },
          { label: 'Any', value: 'any' },
        ],
        required: false,
      },
    ])
  })
})

describe('paramFields for the task completed trigger', () => {
  it('takes an optional agent and checks for the outcomes', () => {
    const fields = paramFields({
      properties: {
        agent_id: {
          anyOf: [{ type: 'string' }, { type: 'null' }],
          default: null,
          description: 'Empty means any agent.',
        },
        outcomes: {
          default: [],
          items: { enum: ['done_acted', 'failed_external'], type: 'string' },
          type: 'array',
        },
      },
      type: 'object',
    })
    expect(fields).toEqual([
      {
        description: 'Empty means any agent.',
        kind: 'source',
        label: 'Agent',
        name: 'agent_id',
        required: false,
        source: 'agent',
      },
      {
        kind: 'checks',
        label: 'Outcomes',
        name: 'outcomes',
        options: [
          { label: 'Done acted', value: 'done_acted' },
          { label: 'Failed external', value: 'failed_external' },
        ],
        required: false,
      },
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

  it('names one item in the singular', () => {
    expect(paramSummary({ conditions: [{}] })).toBe('1 condition')
    expect(paramSummary({ branches: ['Yes'] })).toBe('1 branch')
    expect(paramSummary({ output_fields: [{}] })).toBe('1 output field')
  })
})

describe('paramFields for a plugin step', () => {
  const schema = {
    properties: {
      datasource: {
        type: 'string',
        'x-imbi-choices': true,
        'x-imbi-depends-on': ['region'],
      },
      integration: {
        type: 'string',
        'x-imbi-plugin': 'grafana',
        'x-imbi-source': 'integration',
      },
      labels: {
        items: { type: 'string' },
        type: 'array',
        'x-imbi-choices': true,
      },
      region: { type: 'string' },
    },
    required: ['integration'],
    type: 'object',
  }

  it('picks the integration from those of the plugin', () => {
    const fields = paramFields(schema, [], 'grafana.gather_metrics')
    expect(fields.find((f) => f.name === 'integration')).toMatchObject({
      kind: 'source',
      plugin: 'grafana',
      required: true,
      source: 'integration',
    })
  })

  it('loads choices for the plugin step, as a multi-select for a list', () => {
    const fields = paramFields(schema, [], 'grafana.gather_metrics')
    expect(fields.find((f) => f.name === 'datasource')).toMatchObject({
      dependsOn: ['region'],
      kind: 'choices',
      multiple: false,
      step: 'grafana.gather_metrics',
    })
    expect(fields.find((f) => f.name === 'labels')).toMatchObject({
      dependsOn: [],
      kind: 'choices',
      multiple: true,
    })
    expect(fields.find((f) => f.name === 'region')?.kind).toBe('text')
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
