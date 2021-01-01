import PropTypes from "prop-types"
import React from "react"

function CRUD({title}) {
  return (
    <div>{title}</div>
  )
}

CRUD.propTypes = {
  title: PropTypes.string.isRequired
}

export default CRUD
