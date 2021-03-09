import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    id: {
      type: 'number'
    },
    project_type_ids: {
      type: 'array',
      items: {
        type: 'number'
      }
    },
    name: {
      type: 'string',
      minLength: 3
    },
    fact_type: {
      type: 'string',
      enum: ['enum', 'free-form', 'range']
    },
    data_type: {
      type: 'string',
      enum: ['boolean', 'date', 'decimal', 'integer', 'string', 'timestamp']
    },
    ui_options: {
      type: 'array',
      items: {
        type: 'string',
        enum: ['display-as-badge', 'display-as-percentage', 'hidden']
      }
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
  required: [
    'project_type_ids',
    'fact_type',
    'data_type',
    'ui_options',
    'weight'
  ]
}

export const propTypes = {
  id: PropTypes.number,
  project_type_ids: PropTypes.arrayOf(PropTypes.number),
  name: PropTypes.string.isRequired,
  fact_type: PropTypes.oneOf(['enum', 'free-form', 'range']).isRequired,
  data_type: PropTypes.oneOf([
    'boolean',
    'date',
    'decimal',
    'integer',
    'string',
    'timestamp'
  ]).isRequired,
  ui_options: PropTypes.arrayOf(
    PropTypes.oneOf(['display-as-badge', 'display-as-percentage', 'hidden'])
  ).isRequired,
  description: PropTypes.string,
  weight: PropTypes.number.isRequired
}
