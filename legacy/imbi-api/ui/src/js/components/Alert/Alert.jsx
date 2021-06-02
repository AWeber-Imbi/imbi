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

class Alert extends React.PureComponent {
  render() {
    return (
      <div
        className={`${alertClass[this.props.level]} ${
          this.props.className !== undefined ? this.props.className : ''
        }`}
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
