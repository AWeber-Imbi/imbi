import PropTypes from 'prop-types'

export const Project = {
  name: PropTypes.string.isRequired,
  owned_by: PropTypes.string.isRequired,
  project_type: PropTypes.string.isRequired,
  data_center: PropTypes.string.isRequired,
  configuration_system: PropTypes.string.isRequired,
  deployment_type: PropTypes.string.isRequired,
  orchestration_system: PropTypes.string.isRequired,
  automations: PropTypes.arrayOf(PropTypes.object),
  dependencies: PropTypes.arrayOf(PropTypes.string),
  links: PropTypes.arrayOf(
    PropTypes.shape({
      link_type: PropTypes.string,
      url: PropTypes.string
    })
  )
}
