import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    name: {
      type: 'string',
      minLength: 3
    },
    description: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    icon_class: {
      type: 'string'
    }
  },
  additionalProperties: false,
  required: ['name', 'icon_class']
}

export const propTypes = {
  name: PropTypes.string.isRequired,
  description: PropTypes.string,
  icon_class: PropTypes.string
}
