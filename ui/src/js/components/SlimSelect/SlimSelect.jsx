import PropTypes from 'prop-types'
import { pure } from 'recompose'
import React, { useEffect, useRef, useState } from 'react'
import SlimSelect from 'slim-select'
import 'slim-select/dist/slimselect.min.css'

const Select = ({
  children,
  onChange,
  options,
  placeholder,
  value,
  ...props
}) => {
  const [currentValue, setCurrentValue] = useState(value)
  const ref = useRef(null)

  useEffect(() => {
    const select = new SlimSelect({
      ...options,
      onChange: (options) => {
        if (options.length === 0) {
          setCurrentValue(null)
        } else if (options.length > 1) {
          const newValue = options
            .map((o) => o.value)
            .filter((v) => v !== currentValue)
          select.set(newValue)
        } else {
          setCurrentValue(options[0].value)
        }
      },
      placeholder: placeholder !== undefined ? placeholder : false,
      select: ref.current,
      showSearch: false
    })
    return () => {
      select.destroy()
    }
  })

  useEffect(() => {
    if (onChange !== undefined && currentValue !== value) onChange(currentValue)
  }, [currentValue])

  return (
    <select
      className="form-input rounded-sm"
      defaultValue={currentValue === null ? undefined : [currentValue]}
      multiple
      ref={ref}
      {...props}>
      <option data-placeholder="true" />
      {children}
    </select>
  )
}
Select.defaultPropTypes = {
  options: {}
}
Select.propTypes = {
  children: PropTypes.array,
  onChange: PropTypes.func,
  options: PropTypes.object,
  placeholder: PropTypes.string,
  value: PropTypes.string,
  props: PropTypes.object
}

const PureSelect = pure(Select)

export { PureSelect as SlimSelect }
