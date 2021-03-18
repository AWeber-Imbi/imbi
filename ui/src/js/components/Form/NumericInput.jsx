import PropTypes from 'prop-types'
import React, { useEffect, useRef, useState } from 'react'

function NumericInput({
  autoFocus,
  disabled,
  hasError,
  maximum,
  minimum,
  name,
  onChange,
  placeholder,
  required,
  step,
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
    <input
      autoComplete={name}
      className={
        'form-input' +
        (hasFocus === false && hasError === true ? ' border-red-700' : '')
      }
      disabled={disabled}
      value={value !== undefined && value !== null ? value.toString() : ''}
      id={'field-' + name}
      max={maximum}
      min={minimum}
      name={name}
      onBlur={(event) => {
        event.preventDefault()
        if (onChange !== undefined)
          onChange(
            name,
            event.target.value === '' ? null : parseInt(event.target.value)
          )
        setHasFocus(false)
      }}
      onChange={(event) => {
        event.preventDefault()
        if (onChange !== undefined)
          onChange(
            name,
            event.target.value === '' ? null : parseInt(event.target.value)
          )
      }}
      onFocus={(event) => {
        event.preventDefault()
        setHasFocus(true)
      }}
      placeholder={placeholder}
      ref={ref}
      required={required}
      step={step}
      type="number"
    />
  )
}
NumericInput.defaultProps = {
  autoFocus: false,
  disabled: false,
  hasError: false,
  required: false,
  step: '1'
}
NumericInput.propTypes = {
  autoFocus: PropTypes.bool,
  disabled: PropTypes.bool,
  hasError: PropTypes.bool,
  maximum: PropTypes.number,
  minimum: PropTypes.number,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  placeholder: PropTypes.string,
  required: PropTypes.bool,
  step: PropTypes.string,
  value: PropTypes.number
}
export { NumericInput }
