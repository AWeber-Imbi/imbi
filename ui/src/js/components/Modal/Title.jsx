import PropTypes from 'prop-types'
import React from 'react'

import { Icon } from '..'

class Title extends React.PureComponent {
  render() {
    return (
      <div className="static">
        <h1 className="text-xl text-gray-500 border-b border-gray-400 pb-2 mb-3">
          {this.props.icon && <Icon className="mr-2" icon={this.props.icon} />}
          {this.props.children}
        </h1>
        {this.props.showClose && (
          <div className="absolute top-2 right-2">
            <button
              className="text-gray-400 hover:text-blue-700"
              onClick={this.props.onClose}>
              <Icon icon="fas times-circle" />
            </button>
          </div>
        )}
      </div>
    )
  }
}
Title.defaultProps = {
  showClose: false
}
Title.propTypes = {
  children: PropTypes.string.isRequired,
  icon: PropTypes.string,
  onClose: PropTypes.func,
  showClose: PropTypes.bool
}
export { Title }
