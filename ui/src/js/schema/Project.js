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
    project_type: {
      type: 'string'
    },
    data_center: {
      type: 'string',
      nullable: true
    },
    environments: {
      type: 'array',
      items: 'string',
      nullable: true
    },
    configuration_system: {
      type: 'string',
      nullable: true
    },
    deployment_type: {
      type: 'string',
      nullable: true
    },
    orchestration_system: {
      type: 'string',
      nullable: true
    },
    automations: {
      type: 'object'
    },
    dependencies: {
      type: 'array',
      items: {
        type: 'string',
        format: 'uuid'
      }
    },
    links: {
      type: 'array',
      items: {
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
  dependencies: PropTypes.arrayOf(PropTypes.string),
  links: PropTypes.arrayOf(
    PropTypes.shape({
      link_type: PropTypes.string.isRequired,
      url: PropTypes.string / isRequired
    })
  )
}
