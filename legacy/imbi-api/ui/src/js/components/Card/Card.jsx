import PropTypes from 'prop-types'
import React from 'react'

class Card extends React.PureComponent {
  render() {
    return (
      <div
        className={`bg-white overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6 ${
          this.props.className !== undefined ? this.props.className : ''
        }`}>
        {this.props.children}
      </div>
    )
  }
}
Card.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.arrayOf(PropTypes.element)
  ]),
  className: PropTypes.string
}
export { Card }
