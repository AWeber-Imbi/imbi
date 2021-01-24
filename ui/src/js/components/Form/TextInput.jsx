import PropTypes from 'prop-types'
import React, { useState } from 'react'

function TextInput({
  autoFocus,
  hasError,
  name,
  onChange,
  placeholder,
  value
}) {
  const [hasFocus, setHasFocus] = useState(false)
  return (
    <input
      autoComplete={name}
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
      type="text"
    />
  )
}

TextInput.defaultProps = {
  autoFocus: false,
  hasError: false
}

TextInput.propTypes = {
  autoFocus: PropTypes.bool,
  hasError: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  placeholder: PropTypes.string,
  value: PropTypes.string
}

export { TextInput }
