import PropTypes from 'prop-types'
import React from 'react'
import { Switch, Route } from 'react-router-dom'

import { Profile } from './Profile'
import { Settings } from './Settings'
import { User as Schema } from '../../schema'

function User({ user }) {
  return (
    <Switch>
      <Route path="/ui/user/profile">
        <Profile user={user} />
      </Route>
      <Route path="/ui/user/settings">
        <Settings />
      </Route>
    </Switch>
  )
}
User.propTypes = {
  user: PropTypes.exact(Schema)
}

export { User }
