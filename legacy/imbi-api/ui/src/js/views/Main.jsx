import PropTypes from 'prop-types'
import React, { Fragment, useContext, useEffect, useState } from 'react'
import { Switch, Route } from 'react-router-dom'
import { useTranslation } from 'react-i18next'

import { Admin, Dashboard, NotFound, User } from '.'
import { Breadcrumbs, Loading } from '../components'
import { Context } from '../state'
import { NewEntry, OperationsLog } from './OperationsLog/'
import { Project } from './Project/'
import { Projects } from './Projects/'
import { useMetadata } from '../metadata'
import { User as UserSchema } from '../schema'

function Main({ user }) {
  const [content, setContent] = useState(<Loading />)
  const [state, dispatch] = useContext(Context)
  const [refreshMetadata, setRefreshMetadata] = useState(false)
  const metadata = useMetadata(refreshMetadata)
  const { t } = useTranslation()

  useEffect(() => {
    dispatch({
      type: 'SET_PAGE',
      payload: {
        title: t('headerNavItems.dashboard'),
        icon: 'fas home',
        showTitle: false,
        url: new URL('/ui', state.baseURL)
      }
    })
  }, [])

  useEffect(() => {
    if (metadata !== undefined) {
      dispatch({
        type: 'SET_METADATA',
        payload: [setRefreshMetadata, metadata]
      })
    }
  }, [metadata])

  useEffect(() => {
    if (state.metadata !== undefined)
      setContent(
        <Fragment>
          <Breadcrumbs />
          <main className="flex-grow flex flex-row z-0">
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
        </Fragment>
      )
  }, [state.metadata])
  return content
}
Main.propTypes = {
  user: PropTypes.exact(UserSchema)
}
export { Main }
