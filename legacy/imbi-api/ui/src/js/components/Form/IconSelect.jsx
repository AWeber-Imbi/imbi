import PropTypes from 'prop-types'
import React, { Fragment, useEffect, useRef, useState } from 'react'

import { Icon } from '../'
import { icons } from '../../icons'

function IconSelect({
  autoFocus,
  hasError,
  name,
  onChange,
  placeholder,
  value
}) {
  const [hasFocus, setHasFocus] = useState(false)
  const [icon, setIcon] = useState(value)
  const ref = useRef(null)
  useEffect(() => {
    if (autoFocus === true) {
      ref.current.focus()
    }
  }, [])
  return (
    <Fragment>
      <Icon className="absolute z-50 ml-3 mt-3" icon={icon} />
      <select
        className={
          'form-input pl-10' +
          (hasFocus === false && hasError === true ? ' border-red-700' : '')
        }
        defaultValue={value}
        id={'field-' + name}
        onBlur={(event) => {
          event.preventDefault()
          setHasFocus(false)
        }}
        onChange={(event) => {
          event.preventDefault()
          setIcon(event.target.value)
          if (onChange !== undefined) onChange(name, event.target.value)
        }}
        onFocus={(event) => {
          event.preventDefault()
          setHasFocus(true)
        }}
        placeholder={placeholder}
        ref={ref}>
        <option value="" />
        {icons.map((icon) => {
          return (
            <option key={'icon-select-' + icon} value={icon}>
              {icon}
            </option>
          )
        })}
      </select>
    </Fragment>
  )
}

IconSelect.defaultProps = {
  autoFocus: false,
  hasError: false
}

IconSelect.propTypes = {
  autoFocus: PropTypes.bool,
  hasError: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  placeholder: PropTypes.string,
  value: PropTypes.string.isRequired
}

export { IconSelect }
