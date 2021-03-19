import PropTypes from 'prop-types'
import React from 'react'

import { Icon } from '..'

const icons = {
  info: 'fas info-circle',
  warning: 'fas exclamation-triangle',
  error: 'fas exclamation-circle',
  success: 'fas check-circle'
}

function Alert({ level, children, className, ...props }) {
  return (
    <div
      className={`alert-${level} ${className !== undefined ? className : ''}`}
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

Alert.propTypes = {
  className: PropTypes.string,
  children: PropTypes.oneOfType([PropTypes.string, PropTypes.object]),
  level: PropTypes.oneOf(['info', 'warning', 'error', 'success']).isRequired
}

export { Alert }
