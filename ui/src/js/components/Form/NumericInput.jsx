import PropTypes from 'prop-types'
import React, { useEffect, useState } from 'react'

function NumericInput({
  autoFocus,
  hasError,
  name,
  onChange,
  placeholder,
  value
}) {
  const numbers = '0123456789'
  const [currentValue, setCurrentValue] = useState(value)
  const [hasFocus, setHasFocus] = useState(false)

  useEffect(() => {
    if (currentValue !== null && currentValue !== '') {
      const newValue = parseInt(currentValue)
      if (isNaN(newValue) === true) {
        setCurrentValue(null)
      } else {
        if (onChange !== undefined && newValue !== value)
          onChange(name, newValue)
      }
    } else {
      if (onChange !== undefined && value !== null) onChange(name, null)
    }
  }, [currentValue])

  return (
    <input
      autoComplete={name}
      autoFocus={autoFocus}
      className={
        'form-input' +
        (hasFocus === false && hasError === true ? ' border-red-700' : '')
      }
      defaultValue={value !== null ? value.toString() : value}
      id={'field-' + name}
      name={name}
      onBlur={(event) => {
        event.preventDefault()
        setCurrentValue(event.target.value)
        setHasFocus(false)
      }}
      onChange={(event) => {
        event.preventDefault()
        setCurrentValue(event.target.value)
      }}
      onFocus={(event) => {
        event.preventDefault()
        setHasFocus(true)
      }}
      onKeyPress={(event) => {
        if (!numbers.includes(event.key)) event.preventDefault()
      }}
      placeholder={placeholder}
      type="text"
    />
  )
}

NumericInput.defaultProps = {
  autoFocus: false,
  hasError: false
}

NumericInput.propTypes = {
  autoFocus: PropTypes.bool,
  hasError: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  placeholder: PropTypes.string,
  value: PropTypes.number
}

export { NumericInput }
