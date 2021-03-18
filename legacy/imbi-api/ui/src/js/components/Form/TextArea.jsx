import PropTypes from 'prop-types'
import React, { useEffect, useRef, useState } from 'react'

function TextArea({
  autoFocus,
  disabled,
  hasError,
  name,
  onChange,
  placeholder,
  required,
  rows,
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
    <textarea
      className={
        'form-input' +
        (hasFocus === false && hasError === true ? ' border-red-700' : '')
      }
      defaultValue={value}
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
      rows={rows}
    />
  )
}
TextArea.defaultProps = {
  autoFocus: false,
  disabled: false,
  hasError: false,
  required: false,
  rows: 3
}
TextArea.propTypes = {
  autoFocus: PropTypes.bool,
  disabled: PropTypes.bool,
  hasError: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  placeholder: PropTypes.string,
  required: PropTypes.bool,
  rows: PropTypes.number,
  value: PropTypes.string
}
export { TextArea }
