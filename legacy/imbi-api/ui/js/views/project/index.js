import React from 'react'

import { Router } from '@reach/router'

import Add from './Add'
import Edit from './Edit'

export default () => (
    <Router>
        <Add path="add" />
        <Edit path="edit/:id" />
    </Router>
)
