import React from 'react'

import PropTypes from 'prop-types'

import Tooltip from '../../Tooltip'

export const propTypes = {
    onClick: PropTypes.func,
    value: PropTypes.string,
}

export default function (props) {
    let idValue = 'delete-' + props.value.replace(/ /gi, '-')
    return (
        <th scope="row" key={'col-' + idValue} className="delete-button">
            <button
                className="btn btn-sm text-danger fa fa-trash"
                id={idValue}
                onClick={(e) => {
                    props.onClick(e.target.value)
                }}
                type="button"
                value={props.value}
            ></button>
            <Tooltip placement="right" target={idValue}>
                Delete &ldquo;{props.value}&rdquo;
            </Tooltip>
        </th>
    )
}
