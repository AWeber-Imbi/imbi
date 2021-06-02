import PropTypes from 'prop-types'
import React from 'react'

import { Icon } from '..'

const alertClass = {
  error: 'bg-red-50 border-red-100 text-red-500',
  info: 'bg-blue-50 border-blue-100 text-blue-700',
  success: 'bg-green-50 border-green-100 text-green-800',
  warning: 'bg-yellow-50 border-yellow-100 text-yellow-700'
}

const icons = {
  error: 'fas exclamation-circle',
  info: 'fas info-circle',
  success: 'fas check-circle',
  warning: 'fas exclamation-triangle'
}

class Alert extends React.PureComponent {
  render() {
    return (
      <div
        className={`border px-6 py-4 rounded-lg text-sm ${
          alertClass[this.props.level]
        } ${this.props.className !== undefined ? this.props.className : ''}`}
        {...this.props}>
        <div className="flex">
          <div className="flex-shrink-0">
            <Icon icon={icons[this.props.level]} />
          </div>
          <div className="ml-3">
            {typeof this.props.children == 'string' ? (
              <h3 className="font-medium">{this.props.children}</h3>
            ) : (
              this.props.children
            )}
          </div>
        </div>
      </div>
    )
  }
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
