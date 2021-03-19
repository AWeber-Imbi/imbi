import PropTypes from 'prop-types'
import React, { useState } from 'react'
import { useHistory } from 'react-router-dom'

import { Icon } from '..'

function Value({ title, icon, value, url }) {
  const history = useHistory()
  const [hovering, setHovering] = useState(false)
  function onClick(event) {
    event.preventDefault()
    history.push(url)
  }
  return (
    <div
      className={
        (url !== undefined ? 'cursor-pointer ' : '') +
        'flex flex-col bg-white overflow-hidden shadow rounded-lg'
      }
      onClick={url !== undefined ? onClick : undefined}
      onMouseEnter={() => {
        setHovering(true)
      }}
      onMouseLeave={() => {
        setHovering(false)
      }}>
      <div className="flex-grow px-4 py-5 sm:p-6">
        <div className="flex items-center">
          <div
            className={
              (hovering
                ? 'bg-blue-200 text-blue-600'
                : 'bg-gray-200 text-blue-400') + ' flex-shrink-0 rounded-md p-3'
            }>
            <Icon icon={icon} />
          </div>
          <div className="ml-3 mt-1 w-0 flex-1">
            <div
              className={
                (hovering ? 'text-blue-700' : 'text-gray-500') +
                ' text-sm font-medium truncate'
              }>
              {title}
              {hovering && (
                <Icon
                  className="ml-3 text-gray-400"
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
    </div>
  )
}

Value.propTypes = {
  title: PropTypes.oneOfType([
    PropTypes.arrayOf(PropTypes.element),
    PropTypes.element,
    PropTypes.string
  ]).isRequired,
  icon: PropTypes.string,
  url: PropTypes.string,
  value: PropTypes.number.isRequired
}

export { Value }
