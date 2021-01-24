import PropTypes from 'prop-types'
import React, { useEffect, useRef, useState } from 'react'

function Select({
  autoFocus,
  hasError,
  multiple,
  name,
  onChange,
  options,
  placeholder,
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
      defaultValue={value}
      id={'field-' + name}
      multiple={multiple}
      name={name}
      onBlur={(event) => {
        event.preventDefault()
        setHasFocus(false)
      }}
      onChange={(event) => {
        event.preventDefault()
        if (onChange !== undefined) onChange(name, event.target.value)
      }}
      onFocus={(event) => {
        event.preventDefault()
        setHasFocus(true)
      }}
      placeholder={placeholder}
      ref={ref}>
      <option value="" />
      {options.map((option) => {
        return (
          <option key={name + '-' + option.value} value={option.value}>
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
  multiple: false
}

Select.propTypes = {
  autoFocus: PropTypes.bool,
  hasError: PropTypes.bool,
  multiple: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  options: PropTypes.arrayOf(
    PropTypes.exact({
      label: PropTypes.string.isRequired,
      value: PropTypes.string.isRequired
    })
  ),
  placeholder: PropTypes.string,
  value: PropTypes.string
}

export { Select }
