import PropTypes from "prop-types"

export const ProjectFactType = {
  id: PropTypes.string.isRequired,
  name: PropTypes.string.isRequired,
  project_type: PropTypes.string.isRequired,
  weight: PropTypes.number.isRequired
}
