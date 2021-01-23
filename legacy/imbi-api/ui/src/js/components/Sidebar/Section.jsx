import PropTypes from 'prop-types'
import React, { useState } from 'react'

function Section({ name, open, children }) {
  const [state, setState] = useState(open)
  const indicatorClasses =
    'h-5 w-5 ml transform text-gray-400 group-hover:text-gray-400 transition-colors ease-in-out duration-150  '

  function onClick(e) {
    e.preventDefault()
    setState(!state)
  }

  return (
    <div className="space-y-1 mt-2">
      <button
        className="bg-white text-gray-600 hover:text-blue-700 group w-full flex items-center pr-2 pt-2 rounded-md focus:outline-none"
        onClick={onClick}>
        <svg
          className={
            state === true ? indicatorClasses + ' rotate-90' : indicatorClasses
          }
          viewBox="0 0 20 20"
          aria-hidden="true">
          <path d="M6 6L14 10L6 14V6Z" fill="currentColor" />
        </svg>
        {name}
      </button>
      <div className={'ml-2 ' + (state === true ? 'visible' : 'hidden')}>
        {children}
      </div>
    </div>
  )
}
Section.displayName = 'SideBarSection'

Section.propTypes = {
  name: PropTypes.string.isRequired,
  open: PropTypes.bool,
  children: PropTypes.arrayOf(PropTypes.node)
}

Section.defaultProps = {
  open: false
}

export { Section }
