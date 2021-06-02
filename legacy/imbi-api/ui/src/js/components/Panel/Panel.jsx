import PropTypes from 'prop-types'
import React from 'react'

class Panel extends React.PureComponent {
  render() {
    return (
      <div
        className={`bg-white shadow rounded-lg p-3 ${
          this.props.className !== undefined ? this.props.className : ''
        }`}>
        {this.props.children}
      </div>
    )
  }
}
Panel.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.node),
    PropTypes.node,
    PropTypes.func
  ]),
  className: PropTypes.string
}
export { Panel }
