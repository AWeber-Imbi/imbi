import PropTypes from 'prop-types'
import React, { Fragment } from 'react'

function Container({ children, title }) {
  return (
    <Fragment>
      {title !== undefined && (
        <h3 className="text-lg leading-6 font-medium text-gray-900">{title}</h3>
      )}
      <div className="mt-5 grid grid-flow-row sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-4">
        {children}
      </div>
    </Fragment>
  )
}
Container.propTypes = {
  children: PropTypes.arrayOf(PropTypes.element).isRequired,
  title: PropTypes.string
}
export { Container }
