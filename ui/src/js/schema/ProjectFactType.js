import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    project_type: {
      type: 'string'
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
  required: ['project_type', 'fact_type', 'weight']
}

export const propTypes = {
  project_type: PropTypes.string.isRequired,
  fact_type: PropTypes.string.isRequired,
  weight: PropTypes.number.isRequired
}
