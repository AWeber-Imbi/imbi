import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    id: {
      type: 'number'
    },
    project_type_id: {
      type: 'number'
    },
    fact_type: {
      type: 'string',
      minLength: 3
    },
    weight: {
      type: 'number',
      minimum: 0,
      maximum: 100
    }
  },
  additionalProperties: false,
  required: ['project_type_id', 'fact_type', 'weight']
}

export const propTypes = {
  id: PropTypes.number,
  project_type_id: PropTypes.string.isRequired,
  fact_type: PropTypes.string.isRequired,
  weight: PropTypes.number.isRequired
}
