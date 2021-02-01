import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    id: {
      type: 'number'
    },
    link_type: {
      type: 'string',
      minLength: 3
    },
    icon_class: {
      type: 'string'
    }
  },
  additionalProperties: false,
  required: ['link_type', 'icon_class']
}

export const propTypes = {
  link_type: PropTypes.string.isRequired,
  icon_class: PropTypes.string
}
