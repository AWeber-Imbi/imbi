import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    id: {
      type: 'number'
    },
    project_type_id: {
      oneOf: [{ type: 'number' }, { type: 'null' }]
    },
    fact_type: {
      type: 'string',
      minLength: 3
    },
    data_type: {
      type: 'string',
      enum: ['boolean', 'date', 'decimal', 'integer', 'string', 'timestamp']
    },
    description: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    weight: {
      type: 'number',
      minimum: 0,
      maximum: 100
    }
  },
  additionalProperties: false,
  required: ['project_type_id', 'fact_type', 'data_type', 'weight']
}

export const propTypes = {
  id: PropTypes.number,
  project_type_id: PropTypes.number,
  fact_type: PropTypes.string.isRequired,
  data_type: PropTypes.oneOf([
    'boolean',
    'date',
    'decimal',
    'integer',
    'string',
    'timestamp'
  ]).isRequired,
  description: PropTypes.string,
  weight: PropTypes.number.isRequired
}
