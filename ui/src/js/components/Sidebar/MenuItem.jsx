import {NavLink} from "react-router-dom"
import PropTypes from "prop-types";
import React from "react"

import {Icon} from ".."

const MenuItem = ({value, to, icon}) => {
  return (
    <NavLink className="sidebar-link" to={to}>
      <div className="inline-block w-6 mr-2 text-center">
        <Icon icon={icon}/>
      </div>
      {value}
    </NavLink>
  )
}

MenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired,
  icon: PropTypes.string.isRequired
}

export default MenuItem
