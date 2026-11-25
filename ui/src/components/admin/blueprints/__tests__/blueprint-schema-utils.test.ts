import { describe, expect, it } from 'vitest'

import { buildJsonSchema, schemaToProperties } from '../blueprint-schema-utils'

describe('blueprint schema round trip', () => {
  it('keeps pattern, multipleOf, and the item format and pattern', () => {
    const schema = {
      properties: {
        budget: { pattern: '^\\d+(\\.\\d{2})?$', type: 'string' },
        owners: {
          items: { format: 'uuid', pattern: '^[0-9a-f-]+$', type: 'string' },
          type: 'array',
        },
        rate: { multipleOf: 0.01, type: 'number' },
      },
      type: 'object',
    }
    expect(buildJsonSchema(schemaToProperties(schema))).toEqual(schema)
  })

  it('drops the item format of non-string items', () => {
    const [prop] = schemaToProperties({
      properties: { counts: { items: { type: 'integer' }, type: 'array' } },
    })
    const built = buildJsonSchema([{ ...prop, itemsFormat: 'uuid' }])
    expect(built.properties).toEqual({
      counts: { items: { type: 'integer' }, type: 'array' },
    })
  })
})
