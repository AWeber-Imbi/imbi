import React from 'react'

import PropTypes from 'prop-types'

import Tooltip from '../../Tooltip'

export const propTypes = {
    checked: PropTypes.bool,
    onChange: PropTypes.func,
    value: PropTypes.string,
}

export default function (props) {
    function onChange(e) {
        if (props.onChange !== undefined) {
            props.onChange(e.target.checked ? 'add' : 'remove', e.target.value)
        }
    }

    let idValue = 'select-' + props.value.replace(/ /gi, '-')

    return (
        <td key={'col-' + idValue} className="table-row-checkbox">
            <input
                checked={props.checked}
                className="form-control"
                id={idValue}
                onChange={onChange}
                type="checkbox"
                value={props.value}
            />
        </td>
    )
}
