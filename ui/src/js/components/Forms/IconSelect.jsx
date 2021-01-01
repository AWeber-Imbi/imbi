import PropTypes from "prop-types"
import React, {Fragment, useState} from "react"

import {Icon} from "../"
import {icons} from "../../icons"

function IconSelect({className, defaultValue, value, ...props}) {
  let initialValue = undefined
  if (value !== undefined)
    initialValue = value
  else if (defaultValue !== undefined)
    initialValue = defaultValue
  const [icon, setIcon] = useState(initialValue)
  return (
    <Fragment>
      <Icon className="absolute z-50 ml-3 mt-3" icon={icon} />
      <select className={className + " pl-10"}
              {...props}
              onChange={(event) => setIcon(event.target.value)}
              value={icon}>
        <option value="">Select</option>
        {icons.map((icon) => {
          return (
            <option key={"icon-select-" + icon} value={icon}>{icon}</option>
          )
        })}
      </select>
    </Fragment>
  )
}

IconSelect.propTypes = {
  className: PropTypes.string,
  defaultValue: PropTypes.string,
  value: PropTypes.string
}

export default IconSelect
