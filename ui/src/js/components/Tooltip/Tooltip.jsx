import PropTypes from 'prop-types'
import React, { useState } from 'react'

function Tooltip({ always, arrowPosition, children, className, value }) {
  const [showTooltip, setShowTooltip] = useState(always)
  let rightMargin = value.length > 12 ? '-ml-20' : '-ml-16'
  const position = arrowPosition === 'left' ? '-ml-3' : rightMargin
  return (
    <div
      className="inline-block"
      onMouseOver={() => setShowTooltip(true)}
      onMouseOut={() => setShowTooltip(always ? true : false)}>
      {children}
      <div
        className={
          (showTooltip === true ? 'visible' : 'hidden') +
          ` absolute z-50 mt text-xs ${className}`
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
        <div
          className={`bg-black z-50 cursor-default text-center rounded text-white px-3 py-2 ${position}`}>
          {value}
        </div>
      </div>
    </div>
  )
}

Tooltip.defaultProps = {
  always: false,
  className: 'ml-4',
  arrowPosition: 'left'
}

Tooltip.propTypes = {
  always: PropTypes.bool,
  arrowPosition: PropTypes.oneOf(['left', 'right']),
  children: PropTypes.any,
  className: PropTypes.string,
  value: PropTypes.string.isRequired
}

export { Tooltip }
