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
    slug: {
      type: 'string',
      minLength: 2
    },
    icon_class: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    maintained_by: {
      oneOf: [{ type: 'array', items: { type: 'string' } }, { type: 'null' }]
    },
    gitlab_group_name: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    }
  },
  additionalProperties: false,
  required: ['name', 'slug']
}

export const Namespace = {
  name: PropTypes.string.isRequired,
  slug: PropTypes.string.isRequired,
  icon_class: PropTypes.string,
  maintained_by: PropTypes.string,
  gitlab_group_name: PropTypes.string
}
