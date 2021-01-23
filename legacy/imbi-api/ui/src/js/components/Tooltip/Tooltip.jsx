import PropTypes from 'prop-types'
import React, { useState } from 'react'

function Tooltip({ children, value }) {
  const [showTooltip, setShowTooltip] = useState(false)
  return (
    <div
      className="inline-block"
      onMouseOver={() => setShowTooltip(true)}
      onMouseOut={() => setShowTooltip(false)}>
      {children}
      <div
        className={
          (showTooltip === true ? 'visible' : 'hidden') +
          ' absolute z-50 mt ml-4 text-xs'
        }
        role="tooltip">
        <svg
          className="text-black bottom-full"
          x="0px"
          y="0px"
          height="10px"
          width="10px"
          xmlSpace="preserve">
          <polygon className="fill-current" points="0,10 5,5 10,10" />
        </svg>
        <div className="bg-black z-50 text-center rounded text-white px-3 py-2 -ml-3">
          {value}
        </div>
      </div>
    </div>
  )
}

Tooltip.propTypes = {
  children: PropTypes.any,
  value: PropTypes.string.isRequired
}

export { Tooltip }
