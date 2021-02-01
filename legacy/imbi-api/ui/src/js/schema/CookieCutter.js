import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    name: {
      type: 'string',
      minLength: 3
    },
    project_type_id: {
      type: 'number'
    },
    type: {
      type: 'string',
      enum: ['dashboard', 'project']
    },
    description: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    url: {
      type: 'string'
    }
  },
  additionalProperties: false,
  required: ['name', 'type', 'project_type_id', 'url']
}

export const propTypes = {
  name: PropTypes.string.isRequired,
  type: PropTypes.oneOf(['dashboard', 'project']).isRequired,
  project_type_id: PropTypes.number.isRequired,
  description: PropTypes.string,
  url: PropTypes.string.isRequired
}
