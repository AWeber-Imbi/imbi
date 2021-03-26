import PropTypes from 'prop-types'
import React from 'react'

import { Icon } from '..'

const alertClass = {
  error: 'alert-error',
  info: 'alert-info',
  success: 'alert-success',
  warning: 'alert-warning'
}

const icons = {
  error: 'fas exclamation-circle',
  info: 'fas info-circle',
  success: 'fas check-circle',
  warning: 'fas exclamation-triangle'
}

function Alert({ level, children, className, ...props }) {
  return (
    <div
      className={`${alertClass[level]} ${
        className !== undefined ? className : ''
      }`}
      {...props}>
      <div className="flex">
        <div className="flex-shrink-0">
          <Icon icon={icons[level]} />
        </div>
        <div className="ml-3">
          {typeof children == 'string' ? (
            <h3 className="font-medium">{children}</h3>
          ) : (
            children
          )}
        </div>
      </div>
    </div>
  )
}
Alert.defaultProps = {
  level: 'info'
}
Alert.propTypes = {
  className: PropTypes.string,
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.object]),
  level: PropTypes.oneOf(['info', 'warning', 'error', 'success']).isRequired
}
export { Alert }
