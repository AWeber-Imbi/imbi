import React, { useState } from 'react'

import PropTypes from 'prop-types'

export const propTypes = {
    className: PropTypes.string,
    disabled: PropTypes.bool,
    error: PropTypes.bool,
    id: PropTypes.string,
    name: PropTypes.string.required,
    options: PropTypes.arrayOf(
        PropTypes.shape({
            label: PropTypes.string,
            value: PropTypes.oneOfType([
                PropTypes.bool,
                PropTypes.number,
                PropTypes.string,
            ]),
        })
    ).required,
    placeholder: PropTypes.string,
    onChangeCallback: PropTypes.func.required,
    required: PropTypes.bool,
    value: PropTypes.string,
}

function optionList(placeholder, values) {
    if (Array.isArray(values) === false) values = []
    return placeholder === undefined
        ? values
        : [{ label: placeholder, value: null }, ...values]
}

export default function (props) {
    const disabled =
        props.disabled || (props.options !== null && props.options.length === 0)
    const options = optionList(props.placeholder, props.options)
    const required =
        props.required && props.options !== null && props.options.length > 0
    return (
        <select
            className={'form-control' + (props.error ? ' is-invalid' : '')}
            disabled={disabled}
            id={props.id}
            name={props.name}
            onChange={props.onChangeCallback}
            required={props.required}
            value={props.value !== null ? props.value : ''}
        >
            {options.map((option) => {
                if (option.value == 'None') return null
                return (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                )
            })}
        </select>
    )
}
