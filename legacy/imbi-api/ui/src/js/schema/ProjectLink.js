import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    link_type: {
      type: 'string'
    },
    url: {
      type: 'string',
      format: 'uri'
    }
  },
  additionalProperties: false,
  required: ['link_type', 'url']
}

export const propTypes = {
  link_type: PropTypes.string.isRequired,
  url: PropTypes.string
}
