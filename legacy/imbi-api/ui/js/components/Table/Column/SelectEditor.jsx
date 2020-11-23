import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'
import { Column } from '../PropTypes'

export const propTypes = {
    ...Column,
    autoFocus: PropTypes.bool,
    blurCallback: PropTypes.func,
    changeCallback: PropTypes.func,
    focusCallback: PropTypes.func,
    keyPressCallback: PropTypes.func,
    rowOffset: PropTypes.number,
}

function optionList(placeholder, values) {
    if (values === undefined) values = []
    return placeholder === undefined
        ? values
        : [{ label: placeholder, value: null }, ...values]
}

export default function (props) {
    const [options, setOptions] = useState(
        optionList(props.placeholder, props.options)
    )
    const [value, setValue] = useState(
        props.value !== undefined ? props.value : null
    )

    useEffect(() => {
        setOptions(optionList(props.placeholder, props.options))
    }, [props.options])

    useEffect(() => {
        setValue(props.value)
    }, [props.value])

    return (
        <select
            autoFocus={props.autoFocus}
            className={
                'form-control form-control-sm' +
                (props.error ? ' is-invalid' : '')
            }
            id={'row-' + props.rowOffset + '-' + props.name}
            name={props.name}
            onBlur={props.blurCallback}
            onChange={props.changeCallback}
            onFocus={props.focusCallback}
            onKeyPress={props.keyPressCallback}
            value={value}
        >
            {options.map((option) => {
                return (
                    <option key={option.value} value={option.value}>
                        {option.label}
                    </option>
                )
            })}
        </select>
    )
}
