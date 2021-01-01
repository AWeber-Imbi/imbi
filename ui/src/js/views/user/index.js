import React from 'react'

import {Router} from '../../components'
import {Profile} from './Profile'

export default () => (
  <Router primary={false}>
    <Profile path="profile"/>
  </Router>
)
