import PropTypes from 'prop-types'
import React, { useEffect, useState } from 'react'
import { Switch, Route } from 'react-router-dom'

import { Admin, Dashboard, NotFound, User } from '.'
import { NewEntry, OperationsLog } from './OperationsLog/'
import { Project } from './Project/'
import { Projects } from './Projects/'
import { User as UserSchema } from '../schema'

import { Loading } from '../components'

import { MetadataContext, useMetadata } from '../metadata'

function Main({ user }) {
  const [refreshMetadata, setRefreshMetadata] = useState(false)
  const metadata = useMetadata(refreshMetadata)
  useEffect(() => {
    if (refreshMetadata === true) setRefreshMetadata(false)
  }, [refreshMetadata])

  if (metadata === undefined) return <Loading />

  return (
    <MetadataContext.Provider
      value={{ ...metadata, refresh: () => setRefreshMetadata(true) }}>
      <main className="flex flex-row flex-grow max-w-full">
        <Switch>
          {user.permissions.includes('admin') && (
            <Route path="/ui/admin">
              <Admin user={user} />
            </Route>
          )}
          <Route path="/ui/operations-log/create">
            <NewEntry user={user} />
          </Route>
          <Route path="/ui/operations-log">
            <OperationsLog user={user} />
          </Route>
          <Route path="/ui/projects/create">
            <Project.Create user={user} />
          </Route>
          <Route path="/ui/projects/:projectId">
            <Project.Detail user={user} />
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
    </MetadataContext.Provider>
  )
}

Main.propTypes = {
  user: PropTypes.exact(UserSchema)
}

export { Main }
