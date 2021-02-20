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
    min_value: {
      type: 'number'
    },
    max_value: {
      type: 'number'
    },
    score: {
      type: 'number',
      minimum: 0,
      maximum: 100
    }
  },
  additionalProperties: false,
  required: ['fact_type_id', 'min_value', 'max_value', 'score']
}

export const propTypes = {
  id: PropTypes.number,
  fact_type_id: PropTypes.number.isRequired,
  min_value: PropTypes.number.isRequired,
  max_value: PropTypes.number.isRequired,
  weight: PropTypes.number.isRequired
}
