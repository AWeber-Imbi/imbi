import PropTypes from 'prop-types'
import React, { useEffect, useRef, useState } from 'react'

function TextInput({
  autoFocus,
  disabled,
  hasError,
  name,
  onChange,
  placeholder,
  required,
  type,
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
      id={'field-' + name}
      name={name}
      onBlur={(event) => {
        event.preventDefault()
        setHasFocus(false)
        if (onChange !== undefined) onChange(name, event.target.value)
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
      ref={ref}
      required={required}
      type={type}
      value={value !== null ? value : ''}
    />
  )
}
TextInput.defaultProps = {
  autoFocus: false,
  disabled: false,
  hasError: false,
  required: false
}
TextInput.propTypes = {
  autoFocus: PropTypes.bool,
  disabled: PropTypes.bool,
  hasError: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  placeholder: PropTypes.string,
  required: PropTypes.bool,
  type: PropTypes.oneOf(['email', 'text', 'url']),
  value: PropTypes.string
}
export { TextInput }
