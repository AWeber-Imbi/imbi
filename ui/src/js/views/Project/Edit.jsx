import PropTypes from 'prop-types'
import React from 'react'

function Edit({ project }) {
  return <div>Edit Content for {project.name}</div>
}

Edit.propTypes = {
  project: PropTypes.object.isRequired
}

export { Edit }
