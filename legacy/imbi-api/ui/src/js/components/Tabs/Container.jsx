import PropTypes from 'prop-types'
import React from 'react'

function Container({ children }) {
  return (
    <div className="py-2 text-gray-400 align-center text-center">
      {children}
    </div>
  )
}

Container.propTypes = {
  children: PropTypes.arrayOf(PropTypes.element)
}

export { Container }
