import PropTypes from 'prop-types'
import React from 'react'

class Footer extends React.PureComponent {
  render() {
    return (
      <div
        className={`mt-5 sm:mt-6 text-right border-t border-t-gray-400 pt-5 mt-5 space-x-3 ${this.props.className}`}>
        {this.props.children}
      </div>
    )
  }
}
Footer.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element
  ]).isRequired,
  className: PropTypes.string
}
export { Footer }
