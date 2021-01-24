import PropTypes from 'prop-types'
import React, { useState } from 'react'

function Select({
  autoFocus,
  hasError,
  name,
  onChange,
  options,
  placeholder,
  value
}) {
  const [hasFocus, setHasFocus] = useState(false)
  return (
    <select
      autoFocus={autoFocus}
      className={
        'form-input' +
        (hasFocus === false && hasError === true ? ' border-red-700' : '')
      }
      defaultValue={value}
      id={'field-' + name}
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
      placeholder={placeholder}>
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
  hasError: false
}

Select.propTypes = {
  autoFocus: PropTypes.bool,
  hasError: PropTypes.bool,
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
