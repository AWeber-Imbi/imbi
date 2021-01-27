import PropTypes from 'prop-types'

export const jsonSchema = {
  $schema: 'http://json-schema.org/draft-07/schema#',
  type: 'object',
  properties: {
    id: {
      type: 'string',
      format: 'uuid'
    },
    name: {
      type: 'string',
      minLength: 3
    },
    slug: {
      type: 'string',
      minLength: 3
    },
    owned_by: {
      type: 'string'
    },
    description: {
      type: 'string'
    },
    project_type: {
      type: 'string'
    },
    data_center: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
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
    },
    configuration_system: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    deployment_type: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    orchestration_system: {
      oneOf: [{ type: 'string' }, { type: 'null' }]
    },
    automations: {
      type: 'object'
    },
    dependencies: {
      oneOf: [
        {
          type: 'array',
          items: {
            type: 'string',
            format: 'uuid'
          }
        },
        { type: 'null' }
      ]
    }
  },
  additionalProperties: false,
  required: ['id', 'name', 'slug', 'owned_by', 'project_type']
}

export const propTypes = {
  id: PropTypes.string.isRequired,
  name: PropTypes.string.isRequired,
  slug: PropTypes.string.isRequired,
  owned_by: PropTypes.string.isRequired,
  project_type: PropTypes.string.isRequired,
  data_center: PropTypes.string,
  environments: PropTypes.arrayOf(PropTypes.string),
  configuration_system: PropTypes.string,
  deployment_type: PropTypes.string,
  orchestration_system: PropTypes.string,
  automations: PropTypes.arrayOf(PropTypes.object),
  dependencies: PropTypes.arrayOf(PropTypes.string)
}
