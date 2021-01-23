import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    name: {
      type: 'string',
      minLength: 3
    },
    group_types: {
      type: 'string',
      enum: ['internal', 'ldap']
    },
    external_id: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    permissions: {
      type: 'array',
      items: {
        type: 'string'
      }
    }
  },
  additionalProperties: false,
  required: ['name', 'group_types']
}

export const propTypes = {
  name: PropTypes.string.isRequired,
  group_type: PropTypes.oneOf(['internal', 'ldap']).isRequired,
  external_id: PropTypes.string,
  permissions: PropTypes.arrayOf(PropTypes.string)
}
