import React, { useState } from 'react'

import { Link } from '@reach/router'
import { Breadcrumb, BreadcrumbItem } from 'reactstrap'
import PropTypes from 'prop-types'

export const propTypes = {
    items: PropTypes.arrayOf(
        PropTypes.shape({
            icon: PropTypes.string,
            path: PropTypes.path,
            title: PropTypes.string,
        })
    ),
}

export default function (props) {
    const initialState = [
        {
            title: 'Home',
            path: '/',
            icon: 'fas fa-home',
            active: props.items === undefined || props.items.length == 0,
        },
    ].concat(props.items === undefined ? [] : props.items)
    initialState[initialState.length - 1].active = true

    const [items, setItems] = useState(initialState)

    return (
        <Breadcrumb>
            {items.map((item) => {
                if (item.active === true) {
                    document.title = 'Imbi - ' + item.title
                }
                const icon =
                    item.icon !== undefined ? (
                        <span className={item.icon} />
                    ) : (
                        ''
                    )
                return (
                    <BreadcrumbItem
                        active={item.active}
                        key={item.path ? item.path : item.title}
                    >
                        {item.path && (
                            <Link to={item.path}>
                                {icon} {item.title}
                            </Link>
                        )}
                        {!item.path && (
                            <>
                                {icon} {item.title}
                            </>
                        )}
                    </BreadcrumbItem>
                )
            })}
        </Breadcrumb>
    )
}
