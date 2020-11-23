import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'

import AddRow from './AddRow'
import { Columns } from './PropTypes'
import Row from './Row'

export const propTypes = {
    addCallback: PropTypes.func,
    columns: Columns.isRequired,
    data: PropTypes.array,
    deleteCallback: PropTypes.func,
    keyField: PropTypes.string,
    selectCallback: PropTypes.func,
    updateCallback: PropTypes.func,
    validationCallback: PropTypes.func,
}

export default function (props) {
    const [data, setData] = useState(props.data)
    useEffect(() => setData(props.data), [props.data])
    let rowOffset = -1
    return (
        <tbody>
            {props.addCallback !== undefined && (
                <AddRow
                    addCallback={props.addCallback}
                    columns={props.columns}
                    validationCallback={props.validationCallback}
                />
            )}
            {data.map((row) => {
                rowOffset += 1
                return (
                    <Row
                        columns={props.columns}
                        data={row}
                        deleteCallback={props.deleteCallback}
                        key={'row-' + rowOffset}
                        keyField={props.keyField}
                        includeTrailingColumn={props.addCallback !== undefined}
                        rowOffset={rowOffset}
                        selectCallback={props.selectCallback}
                        updateCallback={props.updateCallback}
                        validationCallback={props.validationCallback}
                    />
                )
            })}
        </tbody>
    )
}
