import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    id: {
      type: 'number'
    },
    namespace_id: {
      type: 'number'
    },
    project_type_id: {
      type: 'number'
    },
    name: {
      type: 'string',
      minLength: 3
    },
    slug: {
      type: 'string',
      minLength: 3
    },
    description: {
      type: 'string'
    },
    environments: {
      oneOf: [
        {
          type: 'array',
          items: {
            type: 'string'
          }
        },
        { type: 'null' }
      ]
    }
  },
  additionalProperties: false,
  required: ['name', 'slug', 'namespace_id', 'project_type_id']
}

export const propTypes = {
  id: PropTypes.number.isRequired,
  namespace_id: PropTypes.number.isRequired,
  project_type_id: PropTypes.number.isRequired,
  name: PropTypes.string.isRequired,
  slug: PropTypes.string.isRequired,
  environments: PropTypes.arrayOf(PropTypes.string)
}
