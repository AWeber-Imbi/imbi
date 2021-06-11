import PropTypes from 'prop-types'
import React, { useContext, useEffect, useState } from 'react'
import { Switch, Route } from 'react-router-dom'

import { Admin, NotFound, User } from '.'
import { Breadcrumbs, ErrorBoundary, Loading } from '../components'
import { ComponentPreviews } from '../components/Components'
import { Context } from '../state'
import { Dashboard } from './Dashboard/Dashboard'
import { NewEntry, OperationsLog } from './OperationsLog/'
import { Project } from './Project/'
import { Projects } from './Projects/'
import { Reports } from './Reports/Reports'
import { useMetadata } from '../metadata'
import { User as UserSchema } from '../schema'

function Main({ user }) {
  const [globalState, dispatch] = useContext(Context)
  const [state, setState] = useState({
    content: <Loading />,
    refreshMetadata: false
  })
  const metadata = useMetadata(state.refreshMetadata)

  useEffect(() => {
    if (metadata !== undefined) {
      dispatch({
        type: 'SET_METADATA',
        payload: [refreshMetadata, metadata]
      })
    }
    setState({ ...state, refreshMetadata: false })
  }, [metadata])

  useEffect(() => {
    if (globalState.metadata !== undefined)
      setState({
        ...state,
        content: (
          <ErrorBoundary>
            <Breadcrumbs />
            <main className="flex-grow flex flex-row z-10">
              <Switch>
                {user.permissions.includes('admin') && (
                  <Route path="/ui/admin">
                    <Admin user={user} />
                  </Route>
                )}
                <Route path="/ui/components">
                  <ComponentPreviews />
                </Route>
                <Route path="/ui/operations-log/create">
                  <NewEntry user={user} />
                </Route>
                <Route path="/ui/operations-log">
                  <OperationsLog user={user} />
                </Route>
                <Route path="/ui/projects/create">
                  <Project.Create user={user} />
                </Route>
                <Route path="/ui/projects/import">
                  <Project.GitlabImport user={user} />
                </Route>
                <Route path="/ui/projects/:projectId">
                  <Project.Detail user={user} />
                </Route>
                <Route path="/ui/projects">
                  <Projects user={user} />
                </Route>
                <Route path="/ui/reports">
                  <Reports user={user} />
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
          </ErrorBoundary>
        )
      })
  }, [globalState.metadata])

  function refreshMetadata() {
    if (state.refreshMetadata === false)
      setState({ ...state, refreshMetadata: true })
  }

  return state.content
}
Main.propTypes = {
  user: PropTypes.exact(UserSchema)
}
export { Main }
