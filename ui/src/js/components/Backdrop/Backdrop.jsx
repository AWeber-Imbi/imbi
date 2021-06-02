import PropTypes from 'prop-types'
import React from 'react'

class Backdrop extends React.PureComponent {
  render() {
    return (
      <div className="fixed inset-0 overflow-y-auto z-50 cursor-not-allowed">
        <div
          className={
            (this.props.wait ? 'cursor-wait ' : '') +
            'flex items-end justify-center min-h-screen pt-4 px-4 pb-20 text-center sm:block sm:p-0'
          }>
          <div className="fixed inset-0 transition-opacity" aria-hidden="true">
            <div className="absolute inset-0 bg-gray-500 opacity-75" />
          </div>
          {this.props.children}
        </div>
      </div>
    )
  }
}
Backdrop.defaultProps = {
  wait: false
}
Backdrop.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.string,
    PropTypes.element
  ]),
  wait: PropTypes.bool
}
export { Backdrop }
