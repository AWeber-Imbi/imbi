import React, { useState } from 'react'

import hash from 'object-hash'
import PropTypes from 'prop-types'
import { TabPane } from 'reactstrap'

export const propTypes = {
    title: PropTypes.string,
}

export default function (props) {
    const [enabled, setEnabled] = useState(false)
    return <TabPane tabId={hash(props.title)}>{props.children}</TabPane>
}
