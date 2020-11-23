import React, { useEffect, useState } from 'react'

import PropTypes from 'prop-types'

import Filter from './Filter'

export const propTypes = {
    filterEnabled: PropTypes.bool,
    filterValueCallback: PropTypes.func,
}

export default function (props) {
    return (
        <div className="toolbar row">
            <div className="col-4">
                <Filter
                    enabled={props.filterEnabled}
                    filterValueCallback={props.filterValueCallback}
                />
            </div>
        </div>
    )
}
