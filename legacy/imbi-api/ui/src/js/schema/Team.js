import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    name: {
      type: 'string',
      minLength: 3
    },
    slug: {
      type: 'string',
      minLength: 3
    },
    icon_class: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    group: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    }
  },
  additionalProperties: false,
  required: ['name', 'slug']
}

export const Team = {
  name: PropTypes.string.isRequired,
  slug: PropTypes.string.isRequired,
  icon_class: PropTypes.string,
  group: PropTypes.string
}
