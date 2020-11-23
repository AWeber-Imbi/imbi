import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'
import { Table } from 'reactstrap'

import Alert from '../Alert'
import Loading from '../Loading'
import Tooltip from '../Tooltip'

import { Columns } from './PropTypes'
import Head from './Head'
import Body from './Body'
import { filterData, sortData } from './Table'
import Toolbar from './Toolbar'

export const propTypes = {
    children: PropTypes.array,
    columns: Columns,
    data: PropTypes.arrayOf(PropTypes.object),
    keyField: PropTypes.string,
    sortChangeCallback: PropTypes.func,
    sortColumn: PropTypes.string,
    sortDirection: PropTypes.oneOf(['asc', 'desc']),
    updateCallback: PropTypes.func,
}

export default function (props) {
    const [filter, setFilter] = useState(null)
    const [sort, setSort] = useState({
        column: props.sortColumn ? props.sortColumn : props.keyField,
        direction: props.sortDirection ? props.sortDirection : 'asc',
    })
    const [values, setValues] = useState([])

    function onSelectCallback(operation, value) {
        if (operation == 'add' && values.find((r) => r == value) === undefined)
            setValues([...values, value])
        if (operation == 'remove') setValues(values.filter((r) => r != value))
    }

    function onSortChange(column, direction) {
        setSort({ column: column, direction: direction })
    }

    useEffect(() => {
        if (props.updateCallback !== undefined) props.updateCallback(values)
    }, [values])

    if (props.data === undefined)
        return (
            <div className="table">
                <Toolbar filterEnabled={false} />
                <Table bordered={false} hover={true} responsive={false} striped>
                    <Head
                        columns={props.columns}
                        multiSelect={true}
                        sortChangeCallback={onSortChange}
                        sortColumn={sort.column}
                        sortDirection={sort.direction}
                    />
                </Table>
                <Loading />
            </div>
        )

    sortData(props.data, props.keyField, sort.column, sort.direction)
    const data = filterData(props.data, filter)
    return (
        <div className="table">
            <Toolbar
                filterEnabled={props.data.length > 0}
                filterValueCallback={setFilter}
            />
            <Table bordered={false} hover={true} responsive={false} striped>
                <Head
                    columns={props.columns}
                    multiSelect={true}
                    sortChangeCallback={onSortChange}
                    sortColumn={sort.column}
                    sortDirection={sort.direction}
                />
                <Body
                    columns={props.columns}
                    data={data}
                    keyField={props.keyField}
                    selectCallback={onSelectCallback}
                    updateCallback={props.updateCallback}
                />
            </Table>
            {props.data.length === 0 &&
                props.children.length > 0 &&
                props.children}
            {filter !== null && filter.length > 0 && data.length == 0 && (
                <Alert color="light" noClose timeout={0}>
                    Your filter &ldquo;{filter}&rdquo; has not matched any
                    values
                </Alert>
            )}
        </div>
    )
}
