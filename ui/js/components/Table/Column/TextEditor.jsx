import React from 'react'

import PropTypes from 'prop-types'
import { Column } from '../PropTypes'

export const propTypes = {
    ...Column,
    autoFocus: PropTypes.bool,
    blurCallback: PropTypes.func,
    changeCallback: PropTypes.func,
    focusCallback: PropTypes.func,
    keyPressCallback: PropTypes.func,
    rowOffset: PropTypes.number,
}

export default function (props) {
    return (
        <input
            autoFocus={props.autoFocus}
            className={
                'form-control form-control-sm' +
                (props.error ? ' is-invalid' : '')
            }
            id={'row-' + props.row + '-' + props.name}
            name={props.name}
            onBlur={props.blurCallback}
            onChange={props.changeCallback}
            onFocus={props.focusCallback}
            onKeyPress={props.keyPressCallback}
            placeholder={props.placeholder}
            style={{ width: '100%' }}
            type="text"
            value={props.value ? props.value : ''}
        />
    )
}
