import PropTypes from "prop-types";
import React, {useState} from 'react'

function Tooltip({children, value}) {
  const [showTooltip, setShowTooltip] = useState(false);
  return (
    <>
      <div className="flex flex-1"
           onMouseOver={() => setShowTooltip(true)}
           onMouseOut={() => setShowTooltip(false)}>
        {children}
      </div>
      <div className={showTooltip === true ? 'visible' : 'hidden'}>
        <div className="absolute z-50 pt-9 -ml-8">
          <svg className="text-black bottom-full" x="0px" y="0px" height="10px" width="10px"
               xmlSpace="preserve">
            <polygon className="fill-current" points="0,10 5,5 10,10"/>
          </svg>
          <div className="bg-black z-50 text-sm -ml-3 rounded text-white p-1 pl-2 pr-2 ">
            {value}
          </div>
        </div>
      </div>
    </>
  )
}

Tooltip.propTypes = {
  children: PropTypes.any,
  value: PropTypes.string.isRequired
}

export default Tooltip
