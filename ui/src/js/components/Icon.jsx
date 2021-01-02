import {FontAwesomeIcon} from "@fortawesome/react-fontawesome"
import PropTypes from "prop-types"
import React from "react"

function Icon({icon, ...props}) {
  if (icon !== undefined && icon !== "")
    return (<FontAwesomeIcon icon={icon.split(" ")} {...props}/>)
  return null
}

Icon.propTypes = {
  icon: PropTypes.string,
  props: PropTypes.object
}

export default Icon
