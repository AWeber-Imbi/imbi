import React from 'react'

import PropTypes from 'prop-types'

import Breadcrumb from './Breadcrumb'

export const propTypes = {
    breadcrumbs: PropTypes.array,
    topBorder: PropTypes.bool,
    topRight: PropTypes.element,
}

export default function (props) {
    return (
        <div className="container-fluid">
            <div className="row align-items-center topbar">
                <div className="col-6">
                    <Breadcrumb items={props.breadcrumbs} />
                </div>
                <div className="col-6 text-right">
                    <div className="float-right">
                        {props.topRight !== undefined ? props.topRight : ''}
                    </div>
                </div>
            </div>
            <div
                className={
                    'container-fluid' + props.topBorder === true
                        ? ' panel-border'
                        : ''
                }
            >
                {props.children}
            </div>
        </div>
    )
}
