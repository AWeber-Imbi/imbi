import PropTypes from 'prop-types'
import React from 'react'

import { IconSelect } from './IconSelect'
import { NumericInput } from './NumericInput'
import { Select } from './Select'
import { TextInput } from './TextInput'
import { TextArea } from './TextArea'

function Field({
  autoFocus,
  description,
  errorMessage,
  maximum,
  minimum,
  multiple,
  name,
  onChange,
  options,
  placeholder,
  required,
  title,
  type,
  value
}) {
  return (
    <div className="sm:grid sm:grid-cols-3 sm:gap-4 sm:items-start sm:pt-5">
      <label
        htmlFor={'field-' + name}
        className="block text-sm font-medium text-gray-700 sm:mt-px sm:pt-2">
        {title}
        {required === true && <sup>*</sup>}
      </label>
      <div className="mt-1 sm:mt-0 sm:col-span-2">
        {type === 'icon' && (
          <IconSelect
            autoFocus={autoFocus}
            hasError={errorMessage !== null}
            name={name}
            onChange={onChange}
            placeholder={placeholder}
            required={required}
            value={value}
          />
        )}
        {type === 'number' && (
          <NumericInput
            autoFocus={autoFocus}
            hasError={errorMessage !== null}
            maximum={maximum}
            minumum={minimum}
            name={name}
            onChange={onChange}
            placeholder={placeholder}
            required={required}
            value={value}
          />
        )}
        {type === 'select' && (
          <Select
            autoFocus={autoFocus}
            hasError={errorMessage !== null}
            multiple={multiple}
            name={name}
            onChange={onChange}
            options={options}
            placeholder={placeholder}
            required={required}
            value={value}
          />
        )}
        {type === 'text' && (
          <TextInput
            autoFocus={autoFocus}
            hasError={errorMessage !== null}
            name={name}
            onChange={onChange}
            placeholder={placeholder}
            required={required}
            value={value}
          />
        )}
        {type === 'textarea' && (
          <TextArea
            autoFocus={autoFocus}
            hasError={errorMessage !== null}
            name={name}
            onChange={onChange}
            placeholder={placeholder}
            required={required}
            value={value}
          />
        )}
        {errorMessage !== null && (
          <p className="mt-2 text-sm text-red-700 col-span-2">{errorMessage}</p>
        )}
        {errorMessage === null && description !== undefined && (
          <p className="mt-2 text-sm text-gray-500 col-span-2">{description}</p>
        )}
      </div>
    </div>
  )
}

Field.defaultProps = {
  autoFocus: false,
  errorMessage: null,
  multiple: false,
  required: false
}

Field.propTypes = {
  autoFocus: PropTypes.bool,
  description: PropTypes.string,
  errorMessage: PropTypes.string,
  maximum: PropTypes.number,
  minimum: PropTypes.number,
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
  required: PropTypes.bool,
  title: PropTypes.string.isRequired,
  type: PropTypes.oneOf(['icon', 'number', 'select', 'text', 'textarea'])
    .isRequired,
  value: PropTypes.oneOfType([PropTypes.number, PropTypes.string])
}

export { Field }
