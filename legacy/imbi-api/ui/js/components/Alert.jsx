import React, { useEffect, useRef, useState } from 'react'

import PropTypes from 'prop-types'
import { Alert } from 'reactstrap'

export const propTypes = {
    children: PropTypes.array,
    color: PropTypes.string,
    noClose: PropTypes.bool,
    timeout: PropTypes.number,
}

const defaultTimeout = 10000

const icons = {
    danger: 'fas fa-exclamation-triangle',
    info: 'fas fa-info-circle',
    light: 'fas fa-exclamation-circle',
    warning: 'fas fa-exclamation-triangle',
    success: 'fas fa-info-circle',
}

export default function (props) {
    const timeoutID = useRef()

    const [display, setDisplay] = useState(false)

    useEffect(() => {
        setDisplay(props.children !== undefined)
    }, [props.children])

    function onToggle(e) {
        e.preventDefault()
        setDisplay(!display)
    }

    useEffect(() => {
        if (
            props.noClose !== true &&
            props.children !== undefined &&
            timeoutID.current === undefined
        ) {
            timeoutID.current = setTimeout(
                () => {
                    setDisplay(false)
                },
                props.timeout !== undefined ? props.timeout : defaultTimeout
            )
        }
        return () => {
            if (timeoutID.current !== undefined) clearTimeout(timeoutID.current)
        }
    }, [props.children, timeoutID])

    if (display === false) return null
    return (
        <Alert
            color={props.color}
            isOpen={true}
            fade={false}
            toggle={props.noClose === true ? null : onToggle}
        >
            <span
                className={
                    props.icon !== undefined ? props.icon : icons[props.color]
                }
            ></span>{' '}
            {props.children}
        </Alert>
    )
}
