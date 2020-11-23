import React from 'react'
import { Link } from '@reach/router'
import PropTypes from 'prop-types'
import { Column } from '../PropTypes'

export const propTypes = {
    ...Column,
    icon: PropTypes.string,
    rowOffset: PropTypes.number,
}

export default function (props) {
    const value =
        props.formatter !== undefined
            ? props.formatter(props.value)
            : props.value
    return (
        <>
            {props.icon !== undefined && props.icon !== false && (
                <span className={'table-row-icon ' + props.icon}></span>
            )}
            {props.name === 'id' && (
                <Link to={`/project/edit/${props.value}`}>
                    <span className={'fas fa-edit'}></span>
                </Link>
            )}
            {props.name !== 'id' && value ? value : null}
        </>
    )
}
