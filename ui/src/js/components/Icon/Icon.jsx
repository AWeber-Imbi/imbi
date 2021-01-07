import {FontAwesomeIcon} from "@fortawesome/react-fontawesome"
import PropTypes from "prop-types"
import React from "react"

function Icon({icon, ...props}) {
  return (<FontAwesomeIcon icon={icon.split(" ")} {...props}/>)
}

Icon.propTypes = {
  icon: PropTypes.string.isRequired,
  props: PropTypes.object
}

export {Icon}

