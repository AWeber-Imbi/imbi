import PropTypes from 'prop-types'
import React from 'react'
import { useHistory } from 'react-router-dom'

function Value({ title, value, url }) {
  const history = useHistory()
  function onClick(event) {
    event.preventDefault()
    history.push(url)
  }
  return (
    <div
      className={
        (url !== undefined ? 'cursor-pointer ' : '') +
        'bg-white overflow-hidden shadow rounded-lg'
      }
      onClick={url !== undefined ? onClick : undefined}>
      <div className="px-4 py-5">
        <div className="text-sm font-medium text-gray-500 truncate">
          {title}
        </div>
        <div className="mt-1 text-3xl font-semibold text-gray-900">
          {value.toLocaleString()}
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
  url: PropTypes.string,
  value: PropTypes.number.isRequired
}

export { Value }
