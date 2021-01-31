import PropTypes from 'prop-types'
import React, { useEffect, useRef, useState } from 'react'

import { SelectOptions } from '../../schema/PropTypes'

function Select({
  autoFocus,
  castTo,
  hasError,
  multiple,
  name,
  onChange,
  options,
  placeholder,
  required,
  value
}) {
  const [hasFocus, setHasFocus] = useState(false)
  const ref = useRef(null)
  useEffect(() => {
    if (autoFocus === true) {
      ref.current.focus()
    }
  }, [])
  return (
    <select
      className={
        'form-input' +
        (hasFocus === false && hasError === true ? ' border-red-700' : '')
      }
      defaultValue={value !== undefined && value !== null ? value.toString() : value}
      id={'field-' + name}
      multiple={multiple}
      name={name}
      onBlur={(event) => {
        event.preventDefault()
        setHasFocus(false)
      }}
      onChange={(event) => {
        event.preventDefault()
        let value = event.target.value
        if (multiple === true) {
          value = Array.from(event.target.selectedOptions, (option) => {
            if (castTo === 'number') parseInt(option.value)
            else option.value
          })
        } else {
          if (castTo === 'number') value = parseInt(value)
        }
        if (onChange !== undefined) onChange(name, value)
      }}
      onFocus={(event) => {
        event.preventDefault()
        setHasFocus(true)
      }}
      placeholder={placeholder}
      ref={ref}
      required={required}>
      {multiple !== true && (
        <option value="">{placeholder !== undefined ? placeholder : ''}</option>
      )}
      {options.map((option) => {
        return (
          <option key={name + '-' + option.value} value={option.value.toString()}>
            {option.label}
          </option>
        )
      })}
    </select>
  )
}

Select.defaultProps = {
  autoFocus: false,
  hasError: false,
  multiple: false,
  required: false
}

Select.propTypes = {
  autoFocus: PropTypes.bool,
  castTo: PropTypes.oneOf(['bool', 'number']),
  hasError: PropTypes.bool,
  multiple: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  options: SelectOptions,
  placeholder: PropTypes.string,
  required: PropTypes.bool,
  value: PropTypes.oneOfType([PropTypes.bool, PropTypes.number, PropTypes.string])
}

export { Select }
