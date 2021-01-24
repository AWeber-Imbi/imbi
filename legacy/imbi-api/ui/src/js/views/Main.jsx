import PropTypes from 'prop-types'
import React from 'react'
import { Switch, Route } from 'react-router-dom'

import { Admin, Dashboard, NotFound, User } from '.'
import { NewEntry, OperationsLog } from './OperationsLog/'
import { NewProject, Projects } from './Projects/'
import { User as UserSchema } from '../schema'

function Main({ user }) {
  return (
    <main className="flex flex-row flex-grow max-h-screen max-w-full">
      <Switch>
        {user.permissions.includes('admin') && (
          <Route path="/ui/admin">
            <Admin user={user} />
          </Route>
        )}
        <Route path="/ui/operations-log/new">
          <NewEntry user={user} />
        </Route>
        <Route path="/ui/operations-log">
          <OperationsLog user={user} />
        </Route>
        <Route path="/ui/projects/new">
          <NewProject user={user} />
        </Route>
        <Route path="/ui/projects">
          <Projects user={user} />
        </Route>
        <Route path="/ui/user">
          <User user={user} />
        </Route>
        <Route path="/ui/">
          <Dashboard user={user} />
        </Route>
        <Route path="*">
          <NotFound />
        </Route>
      </Switch>
    </main>
  )
}

Main.propTypes = {
  user: PropTypes.exact(UserSchema)
}

export { Main }
