import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    id: {
      type: 'number'
    },
    fact_type_id: {
      type: 'number'
    },
    icon_class: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    value: {
      oneOf: [{ type: 'boolean' }, { type: 'number' }, { type: 'string' }]
    },
    score: {
      type: 'number',
      minimum: 0,
      maximum: 100
    }
  },
  additionalProperties: false,
  required: ['fact_type_id', 'value']
}

export const propTypes = {
  id: PropTypes.number,
  fact_type_id: PropTypes.number.isRequired,
  icon_class: PropTypes.string,
  value: PropTypes.oneOfType([
    PropTypes.bool,
    PropTypes.number,
    PropTypes.string
  ]).isRequired,
  weight: PropTypes.number.isRequired
}
