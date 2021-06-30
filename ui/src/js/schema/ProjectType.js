import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    id: {
      type: 'number'
    },
    name: {
      type: 'string',
      minLength: 3
    },
    plural_name: {
      type: 'string',
      minLength: 3
    },
    slug: {
      type: 'string',
      minLength: 3
    },
    description: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    icon_class: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    environment_urls: {
      type: 'boolean'
    },
    gitlab_project_prefix: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    }
  },
  additionalProperties: false,
  required: ['name']
}

export const propTypes = {
  id: PropTypes.number,
  name: PropTypes.string.isRequired,
  plural_name: PropTypes.string.isRequired,
  slug: PropTypes.string.isRequired,
  description: PropTypes.string,
  icon_class: PropTypes.string,
  environment_urls: PropTypes.bool,
  gitlab_project_prefix: PropTypes.string
}
