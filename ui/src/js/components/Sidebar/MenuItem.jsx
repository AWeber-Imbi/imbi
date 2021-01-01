import {Link} from "@reach/router"
import PropTypes from "prop-types";
import React from "react"

import {Icon} from ".."

const classes = "group w-full flex items-center p-2 text-sm text-gray-600 rounded-md hover:text-blue-700 hover:bg-gray-50"
const itemClasses = {
  true: classes + " font-bold",
  false: classes
}

const MenuItem = ({value, to, icon}) => {
  return (
    <Link getProps={({isCurrent}) => {return {className: itemClasses[isCurrent]}}}
          key={to.replace(/\//gi, "_") + "-nav-item"}
          to={to}>
      <div className="inline-block w-6 mr-2 text-center">
        <Icon icon={icon}/>
      </div>
      {value}
    </Link>
  )
}

MenuItem.propTypes = {
  value: PropTypes.string.isRequired,
  to: PropTypes.string.isRequired,
  icon: PropTypes.string.isRequired
}

export default MenuItem
