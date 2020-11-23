import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'

import { Columns } from './PropTypes'
import { Column } from './Column/'

export const propTypes = {
    addCallback: PropTypes.func,
    columns: Columns.isRequired,
    validationCallback: PropTypes.func,
}

export default function (props) {
    const [addDisabled, setAddDisabled] = useState(true)
    const [columnErrors, setColumnErrors] = useState([])
    const [editingColumn, setEditingColumn] = useState(null)
    const [data, setData] = useState(props.data ? props.data : {})

    function onAdd(e) {
        e.preventDefault()
        props.addCallback(data)
        setData({})
    }

    function onUpdate(name, value) {
        setData({ ...data, [name]: value })
    }

    useEffect(() => {
        if (props.validationCallback !== undefined) {
            setColumnErrors(
                props
                    .validationCallback(data)
                    .filter((v) => v !== editingColumn)
            )
        }
    }, [data])

    useEffect(() => {
        if (columnErrors.length > 0) {
            if (addDisabled === false) setAddDisabled(true)
            return
        }
        const vc = props.columns
            .map((column) => {
                if (column.required === false) return true
                return (
                    data[column.name] !== undefined &&
                    data[column.name] !== null &&
                    data[column.name].length > 0
                )
            })
            .every((value) => value)
        setAddDisabled(vc === false)
    }, [data, columnErrors])

    let colOffset = -1
    let columns = props.columns.map((column) => {
        let value = data[column.name]
        if (value === undefined && column.type == 'select') {
            if (column.placeholder !== undefined) value = column.placeholder
            else if (column.options.length > 0) value = column.options[0].value
        }
        colOffset += 1
        return (
            <Column
                {...column}
                autoFocus={colOffset == 0}
                changeCallback={onUpdate}
                editable={true}
                editingCallback={setEditingColumn}
                editing={true}
                error={columnErrors.findIndex((e) => e == column.name) >= 0}
                icon={column.isIcon === true && data[column.name]}
                key={'row-' + props.rowOffset + '-col-' + colOffset}
                required={column.required}
                rowEdit={true}
                rowOffset={0}
                value={value}
                updateCallback={onUpdate}
            />
        )
    })

    return (
        <tr>
            <th className="delete-button" scope="row">
                {' '}
            </th>
            {columns}
            <td className="add-button">
                <button
                    className="btn btn-small btn-primary"
                    disabled={addDisabled}
                    onClick={onAdd}
                >
                    Add
                </button>
            </td>
        </tr>
    )
}
