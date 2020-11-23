import React from 'react'
import { Router } from '@reach/router'

import { Profile } from './Profile'

export default () => (
    <Router>
        <Profile path="profile" />
    </Router>
)
