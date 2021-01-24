import PropTypes from 'prop-types'
import React, { useState } from 'react'

function TextArea({
  autoFocus,
  hasError,
  name,
  onChange,
  placeholder,
  rows,
  value
}) {
  const [hasFocus, setHasFocus] = useState(false)
  return (
    <textarea
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
      rows={rows}
    />
  )
}

TextArea.defaultProps = {
  autoFocus: false,
  hasError: false,
  rows: 3
}

TextArea.propTypes = {
  autoFocus: PropTypes.bool,
  hasError: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  placeholder: PropTypes.string,
  rows: PropTypes.number,
  value: PropTypes.string
}

export { TextArea }
