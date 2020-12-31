import {FontAwesomeIcon} from "@fortawesome/react-fontawesome";
import {
  faExclamationCircle, faInfoCircle, faExclamationTriangle,
  faCheckCircle
} from '@fortawesome/free-solid-svg-icons'
import PropTypes from "prop-types";
import React from 'react'

const icons = {
  info: faInfoCircle,
  warning: faExclamationTriangle,
  error: faExclamationCircle,
  success: faCheckCircle
}

function Alert({level, children}) {
  return (
    <div className={'alert-' + level}>
      <div className="flex">
        <div className="flex-shrink-0">
          <FontAwesomeIcon icon={icons[level]}/>
        </div>
        <div className="ml-3">
          {typeof children == 'string' ? (<h3 className="font-medium">{children}</h3>) : children}
        </div>
      </div>
    </div>
  )
}

Alert.propTypes = {
  level: PropTypes.oneOf(['info', 'warning', 'error', 'success']).isRequired,
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.object])
}

export default Alert
