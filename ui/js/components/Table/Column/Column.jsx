import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'

import { Column } from '../PropTypes'
import SelectEditor from './SelectEditor'
import Text from './Text'
import TextEditor from './TextEditor'

export const propTypes = {
    ...Column,
    autoFocus: PropTypes.bool,
    rowEdit: PropTypes.bool,
    rowOffset: PropTypes.number,
}

export default function (props) {
    const [editing, setEditing] = useState(
        props.editing || props.rowEdit === true || props.error === true
    )
    const [options, setOptions] = useState(props.options)
    const [value, setValue] = useState(props.value)

    useEffect(() => {
        if (editing === false && props.error === true) setEditing(true)
    }, [props.error])

    useEffect(() => {
        setOptions(props.options)
    }, [props.options])

    useEffect(() => {
        if (
            (props.rowEdit === true || editing === false) &&
            props.value != value
        )
            setValue(props.value)
    }, [props.value])

    useEffect(() => {
        if (props.changeCallback !== undefined)
            props.changeCallback(props.name, value)
    }, [value])

    function onBlur(e) {
        if (!props.editable || !editing) return
        setValue(value)
        if (props.editingCallback !== undefined) props.editingCallback(null)
        if (props.updateCallback !== undefined) {
            if (props.rowEdit !== true) setEditing(false)
            props.updateCallback(props.name, value)
        }
    }

    function onClick(e) {
        e.preventDefault()
        if (!props.editable) return
        if (!editing) setEditing(true)
        if (props.editingCallback !== undefined)
            props.editingCallback(props.name)
    }

    function onChange(e) {
        if (!props.editable || !editing) return
        setValue(e.target.value)
    }

    function onFocus(e) {
        if (props.editingCallback !== undefined)
            props.editingCallback(props.name)
    }

    function onKeyPress(e) {
        if (!e) e = window.event
        var value = e.keyCode || e.which
        if (value === 13) {
            onBlur(e)
        }
    }

    return (
        <td onClick={onClick} style={props.style}>
            {props.rowEdit !== true && !editing && (
                <Text {...props} value={value} />
            )}
            {(props.rowEdit || editing) && props.type == 'select' && (
                <SelectEditor
                    autoFocus={props.autoFocus}
                    blurCallback={onBlur}
                    changeCallback={onChange}
                    focusCallback={onFocus}
                    error={props.error}
                    keyPressCallback={onKeyPress}
                    name={props.name}
                    options={options}
                    placeholder={props.placeholder}
                    required={props.required}
                    rowOffset={props.rowOffset}
                    value={value}
                />
            )}
            {(props.rowEdit || editing) && props.type != 'select' && (
                <TextEditor
                    autoFocus={props.autoFocus}
                    blurCallback={onBlur}
                    changeCallback={onChange}
                    error={props.error}
                    focusCallback={onFocus}
                    keyPressCallback={onKeyPress}
                    name={props.name}
                    placeholder={props.placeholder}
                    required={props.required}
                    rowOffset={props.rowOffset}
                    value={value !== undefined ? value : ''}
                />
            )}
            {props.error && props.errorHelp && (
                <div className="invalid-feedback">{props.errorHelp}</div>
            )}
        </td>
    )
}
