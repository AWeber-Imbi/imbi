import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'

import { Columns } from './PropTypes'
import { CheckboxColumn, Column, DeleteColumn } from './Column/'
import SelectEditor from './Column/Column'

export const propTypes = {
    columns: Columns,
    data: PropTypes.arrayOf(PropTypes.object),
    deleteCallback: PropTypes.func,
    keyField: PropTypes.string,
    rowOffset: PropTypes.number,
    selectCallback: PropTypes.func,
    updateCallback: PropTypes.func,
    validationCallback: PropTypes.func,
}

export default function (props) {
    const [checked, setChecked] = useState(false)
    const [columnError, setColumnError] = useState(undefined)
    const [columns, setColumns] = useState(props.columns)
    const [rowData, setRowData] = useState(props.data)

    useEffect(() => {
        setColumns(props.columns)
    }, [props.columns])

    useEffect(() => {
        if (!columnError && props.data !== rowData) setRowData(props.data)
    }, [props.data])

    function onUpdate(column, value) {
        if (rowData[column] == value) return
        let updatedRowData = { ...rowData }
        updatedRowData[column] = value
        setRowData(updatedRowData)
        if (props.validationCallback) {
            const result = props.validationCallback(updatedRowData)
            if (result.state === 'column_error') {
                setColumnError(result.column)
                return
            }
            if (result.state === 'update_column') {
                updatedRowData[result.column] = result.value
                setRowData(updatedRowData)
            }
        }
        setColumnError(undefined)
        props.updateCallback(props.data[props.keyField], updatedRowData)
    }

    let colOffset = -1
    let cols = columns.map((column) => {
        colOffset += 1
        return (
            <Column
                autoFocus={false}
                default={column.default}
                editable={column.editable}
                error={columnError == column.name}
                errorHelp={column.errorHelp}
                formatter={column.formatter}
                icon={column.isIcon === true && rowData[column.name]}
                key={'row-' + props.rowOffset + '-col-' + colOffset}
                name={column.name}
                options={column.options}
                rowOffset={props.rowOffset}
                style={column.style}
                type={column.type}
                updateCallback={onUpdate}
                value={rowData[column.name]}
            />
        )
    })

    if (props.deleteCallback !== undefined) {
        cols = [
            <DeleteColumn
                key={'row-' + props.rowOffset + '-delete'}
                onClick={props.deleteCallback}
                value={props.data[props.keyField]}
            />,
            ...cols,
        ]
    }

    if (props.includeTrailingColumn === true)
        cols = [
            ...cols,
            <td
                className="add-button"
                key={'row-' + props.rowOffset + '-trailing'}
            ></td>,
        ]

    function onChange(operation, value) {
        setChecked(operation == 'add')
        props.selectCallback(operation, value)
    }

    if (props.selectCallback !== undefined) {
        cols = [
            <CheckboxColumn
                checked={checked}
                key={'row-' + props.rowOffset + '-checkbox'}
                onChange={onChange}
                value={props.data[props.keyField]}
            />,
            ...cols,
        ]
    }

    function onRowClick(e) {
        if (e.target.tagName == 'TD') {
            const operation = checked ? 'remove' : 'add'
            setChecked(!checked)
            props.selectCallback(
                operation,
                e.target.parentElement.dataset.value
            )
        }
    }

    return (
        <tr
            data-value={
                props.selectCallback !== undefined
                    ? props.data[props.keyField]
                    : undefined
            }
            onClick={
                props.selectCallback !== undefined ? onRowClick : undefined
            }
        >
            {cols}
        </tr>
    )
}
