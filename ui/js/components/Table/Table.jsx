import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'
import { Table } from 'reactstrap'

import Alert from '../Alert'
import Loading from '../Loading'
import Tooltip from '../Tooltip'

import { Columns } from './PropTypes'
import Head from './Head'
import Body from './Body'
import Toolbar from './Toolbar'

export const propTypes = {
    addCallback: PropTypes.func,
    children: PropTypes.element,
    columns: Columns.isRequired,
    data: PropTypes.arrayOf(PropTypes.object),
    deleteCallback: PropTypes.func,
    hideFilter: PropTypes.bool,
    includeDelete: PropTypes.bool,
    keyField: PropTypes.string.isRequired,
    size: PropTypes.string,
    sortChangeCallback: PropTypes.func,
    sortColumn: PropTypes.string,
    sortDirection: PropTypes.oneOf(['asc', 'desc']),
    updateCallback: PropTypes.func,
    validationCallback: PropTypes.func,
}

export function filterData(data, filter) {
    if (filter === null || !filter) return data
    return data.filter((row) => {
        const found = Object.values(row).map((column) => {
            if (typeof column == 'string') {
                return column.toLowerCase().includes(filter)
            }
            return false
        })
        return found.some(function (e) {
            return e
        })
    })
}

export function sortData(data, keyField, sortColumn, sortDirection) {
    if (data === undefined) return undefined
    return [...data].sort((a, b) => {
        if (sortDirection == 'asc') {
            if (a[sortColumn] < b[sortColumn]) return -1
            if (a[sortColumn] > b[sortColumn]) return 1
            // First two fields match, sort on keyField value next
            if (a[keyField] < b[keyField]) return -1
            if (a[keyField] > b[keyField]) return 1
            return 1
        }
        if (a[sortColumn] < b[sortColumn]) return 1
        if (a[sortColumn] > b[sortColumn]) return -1
        // First two fields match, sort on keyField value next
        if (a[keyField] < b[keyField]) return 1
        if (a[keyField] > b[keyField]) return -1
        return -1
    })
}

export default function (props) {
    const [columns, setColumns] = useState(props.columns)
    const [filter, setFilter] = useState(null)
    const [sort, setSort] = useState({
        column: props.sortColumn,
        direction: props.sortDirection,
    })
    useEffect(() => {
        setSort({ column: props.sortColumn, direction: props.sortDirection })
    }, [props.sortColumn, props.sortDirection])

    const [data, setData] = useState(
        sortData(
            filterData(props.data, filter),
            props.keyField,
            sort.column,
            sort.direction
        )
    )

    useEffect(() => {
        setData(
            sortData(
                filterData(props.data, filter),
                props.keyField,
                sort.column,
                sort.direction
            )
        )
    }, [props.data, sort.column, sort.direction, props.keyField])

    useEffect(() => {
        setColumns(props.columns)
    }, [props.columns])

    useEffect(() => {
        setData(
            sortData(
                filterData(props.data, filter),
                props.keyField,
                sort.column,
                sort.direction
            )
        )
    }, [props.data, sort, filter])

    if (data === undefined)
        return (
            <div className="table">
                {props.hideFilter !== true && <Toolbar filterEnabled={false} />}
                <Table bordered={false} hover={true} responsive={true} striped>
                    <Head
                        columns={columns}
                        includeAddRow={props.addCallback !== undefined}
                        includeDelete={props.deleteCallback !== undefined}
                        sortChangeCallback={onSortChange}
                        sortColumn={sort.column}
                        sortDirection={sort.direction}
                    />
                </Table>
                <Loading />
            </div>
        )

    function onSortChange(column, direction) {
        setSort({ column: column, direction: direction })
    }

    return (
        <div className="table">
            {props.hideFilter !== true && (
                <Toolbar
                    filterEnabled={props.data.length > 0}
                    filterValueCallback={setFilter}
                />
            )}
            <Table bordered={false} hover={true} responsive={true} striped>
                <Head
                    columns={columns}
                    includeAddRow={props.addCallback !== undefined}
                    includeDelete={props.deleteCallback !== undefined}
                    sortChangeCallback={onSortChange}
                    sortColumn={sort.column}
                    sortDirection={sort.direction}
                />
                <Body
                    addCallback={props.addCallback}
                    addRowEnabled={props.addRowEnabled}
                    columns={columns}
                    data={data}
                    deleteCallback={props.deleteCallback}
                    keyField={props.keyField}
                    updateCallback={props.updateCallback}
                    validationCallback={props.validationCallback}
                />
            </Table>
            {props.data.length === 0 && props.children}
            {data.length > 0 && (
                <div className="text-muted caption">
                    <strong>Tip:</strong> Click to edit, press return to save
                    your changes
                </div>
            )}
            {filter !== null && filter.length > 0 && data.length == 0 && (
                <Alert color="light" noClose timeout={0}>
                    Your filter &ldquo;{filter}&rdquo; has not matched any
                    values
                </Alert>
            )}
        </div>
    )
}
