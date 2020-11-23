import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'

import Tooltip from '../Tooltip'

import { Columns } from './PropTypes'

export const propTypes = {
    columns: Columns.required,
    includeAddRow: PropTypes.bool,
    includeDelete: PropTypes.bool,
    multiSelect: PropTypes.bool,
    sortChangeCallback: PropTypes.func,
    sortColumn: PropTypes.string,
    sortDirection: PropTypes.oneOf(['asc', 'desc']),
}

const sortIcon = {
    asc: 'sort fa fa-caret-up',
    desc: 'sort fa fa-caret-down',
}

export default function (props) {
    const [sort, setSort] = useState({
        column: props.sortColumn,
        direction: props.sortDirection,
    })

    useEffect(() => {
        if (props.sortChangeCallback !== undefined)
            props.sortChangeCallback(sort.column, sort.direction)
    }, [sort.column, sort.direction])

    function sortChangeCallback(e) {
        const column = e.target.dataset.column
        const direction = sort.direction == 'asc' ? 'desc' : 'asc'
        setSort({
            column: e.target.dataset.column,
            direction:
                e.target.dataset.column != sort.column ? 'asc' : direction,
        })
    }

    let columns =
        props.includeDelete || props.multiSelect
            ? [
                  <th
                      className="table-empty-header delete-button"
                      key="empty-column-header"
                  >
                      {' '}
                  </th>,
              ]
            : []
    columns = columns.concat(
        props.columns.map((column) => {
            let sortDirection = 'Z-A'
            if (column.name == sort.column && sort.direction == 'asc')
                sortDirection = 'A-Z'
            return (
                <th
                    key={column.name}
                    data-column={column.name}
                    onClick={
                        column.sortable === true
                            ? sortChangeCallback
                            : undefined
                    }
                    id={'th-' + column.name}
                    scope="col"
                    style={column.headerStyle}
                >
                    <span data-column={column.name}>{column.title}</span>
                    {column.sortable === true && sort.column == column.name && (
                        <button
                            className={sortIcon[sort.direction]}
                            data-column={column.name}
                            onClick={sortChangeCallback}
                        />
                    )}
                    {column.sortable === true && (
                        <Tooltip placement="top" target={'th-' + column.name}>
                            Sort {sortDirection}
                        </Tooltip>
                    )}
                </th>
            )
        })
    )
    if (props.includeAddRow === true)
        columns = columns.concat(
            <th key="table-add-button-column" className="add-button"></th>
        )
    return (
        <thead>
            <tr>{columns}</tr>
        </thead>
    )
}
