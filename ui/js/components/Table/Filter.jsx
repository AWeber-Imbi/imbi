import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'

export const propTypes = {
    enabled: PropTypes.bool,
    filterValueCallback: PropTypes.func,
}

export default function (props) {
    const [value, setValue] = useState(null)

    useEffect(() => {
        if (props.filterValueCallback !== undefined)
            props.filterValueCallback(value)
    }, [value])

    return (
        <div className="input-group filter">
            <div className="input-group-prepend">
                <div className="input-group-text">
                    <span
                        className="fas fa-filter"
                        style={{ color: value ? '#0a0' : '#888' }}
                    />
                </div>
            </div>
            <input
                className="form-control form-control-sm"
                onChange={(e) => {
                    setValue(e.target.value.toLowerCase())
                }}
                disabled={!props.enabled}
                type="text"
                placeholder="Filter"
                value={value ? value : ''}
            />
        </div>
    )
}
