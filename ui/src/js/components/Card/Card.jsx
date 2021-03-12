import PropTypes from 'prop-types'
import React from 'react'

function Card({ children, className }) {
  return (
    <div
      className={`bg-white overflow-hidden shadow rounded-lg px-4 py-5 sm:p-6 ${
        className !== undefined ? className : ''
      }`}>
      {children}
    </div>
  )
}
Card.propTypes = {
  children: PropTypes.oneOfType([
    PropTypes.element,
    PropTypes.arrayOf(PropTypes.element)
  ]),
  className: PropTypes.string
}
export { Card }
