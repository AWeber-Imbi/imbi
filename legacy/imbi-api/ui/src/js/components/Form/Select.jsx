import PropTypes from 'prop-types'
import React, { useEffect, useRef, useState } from 'react'

import { SelectOptions } from '../../schema/PropTypes'

function Select({
  autoFocus,
  castTo,
  disabled,
  hasError,
  multiple,
  name,
  onChange,
  options,
  placeholder,
  required,
  value
}) {
  function _defaultValue() {
    if (multiple === true && (value === undefined || value === null)) return []
    if (multiple === true && castTo === 'number')
      return value.map((item) => parseInt(item))
    if (value === undefined || value === null || value === '') return null
    if (castTo === 'number') return parseInt(value)
    return value
  }

  const [hasFocus, setHasFocus] = useState(false)
  const ref = useRef(null)
  const [currentValue, setCurrentValue] = useState(_defaultValue())

  useEffect(() => {
    if (autoFocus === true) {
      ref.current.focus()
    }
  }, [])

  useEffect(() => {
    if (onChange !== undefined)
      onChange(name, currentValue === '' ? null : currentValue)
  }, [currentValue])

  return (
    <select
      className={
        'form-input' +
        (multiple === false ? ' truncate pr-6' : '') +
        (hasFocus === false && hasError === true ? ' border-red-700' : '')
      }
      defaultValue={currentValue === null ? '' : currentValue}
      disabled={disabled}
      id={'field-' + name}
      multiple={multiple}
      name={name}
      onBlur={(event) => {
        event.preventDefault()
        setHasFocus(false)
      }}
      onChange={(event) => {
        event.preventDefault()
        let targetValue = event.target.value
        if (multiple === true) {
          targetValue = Array.from(event.target.selectedOptions, (option) => {
            return castTo === 'number' ? parseInt(option.value) : option.value
          })
          targetValue.sort()
        } else {
          if (castTo === 'number')
            targetValue =
              targetValue !== '' ? parseInt(targetValue) : targetValue
        }
        setCurrentValue(targetValue === '' ? null : targetValue)
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
          <option
            key={name + '-' + option.value}
            value={
              option.value !== null ? option.value.toString() : option.value
            }>
            {option.label}
          </option>
        )
      })}
    </select>
  )
}
Select.defaultProps = {
  autoFocus: false,
  disabled: false,
  hasError: false,
  multiple: false,
  required: false
}
Select.propTypes = {
  autoFocus: PropTypes.bool,
  disabled: PropTypes.bool,
  castTo: PropTypes.oneOf(['number']),
  hasError: PropTypes.bool,
  multiple: PropTypes.bool,
  name: PropTypes.string.isRequired,
  onChange: PropTypes.func,
  options: SelectOptions,
  placeholder: PropTypes.string,
  required: PropTypes.bool,
  value: PropTypes.oneOfType([
    PropTypes.array,
    PropTypes.bool,
    PropTypes.number,
    PropTypes.string
  ])
}
export { Select }
