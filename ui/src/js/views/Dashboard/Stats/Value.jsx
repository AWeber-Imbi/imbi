import { Link } from 'react-router-dom'
import PropTypes from 'prop-types'
import React, { useState } from 'react'

import { Icon } from '../../../components'

function Value({ title, icon, value, url }) {
  const [hovering, setHovering] = useState(false)
  return (
    <Link
      className="flex flex-col bg-white overflow-hidden shadow rounded-lg hover:bg-blue-100 hover:text-blue-700"
      onMouseEnter={() => {
        setHovering(true)
      }}
      onMouseLeave={() => {
        setHovering(false)
      }}
      to={url}>
      <div className="flex-grow px-4 py-5 sm:p-6">
        <div className="flex items-center">
          <div className="bg-gray-200 flex-shrink-0 rounded-md p-3 text-blue-600">
            <Icon icon={icon} />
          </div>
          <div className="ml-3 mt-1 w-0 flex-1">
            <div className="font-medium text-sm text-gray-600 truncate">
              {title}
              {hovering && (
                <Icon
                  className="ml-3 text-gray-600"
                  icon="fas external-link-alt"
                />
              )}
            </div>
            <div className="flex items-baseline">
              <div className="text-2xl font-semibold text-gray-700">
                {value.toLocaleString()}
              </div>
            </div>
          </div>
        </div>
      </div>
    </Link>
  )
}
Value.propTypes = {
  title: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element,
    PropTypes.string
  ]).isRequired,
  icon: PropTypes.string.isRequired,
  url: PropTypes.string.isRequired,
  value: PropTypes.number.isRequired
}
export { Value }
