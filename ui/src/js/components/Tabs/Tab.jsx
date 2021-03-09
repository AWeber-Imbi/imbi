import { NavLink, useRouteMatch } from 'react-router-dom'
import PropTypes from 'prop-types'
import React from 'react'

const active =
  'border-blue-500 text-blue-700 whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm focus:border-0'
const inactive =
  'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300 whitespace-nowrap py-4 px-1 border-b-2 font-medium text-sm'

function Tab({ target, children }) {
  let match = useRouteMatch({
    path: target,
    exact: true
  })
  return (
    <NavLink className={match ? active : inactive} to={target}>
      {children}
    </NavLink>
  )
}

Tab.propTypes = {
  children: PropTypes.string.isRequired,
  target: PropTypes.string.isRequired
}

export { Tab }
