import { BrowserRouter as Router } from 'react-router-dom'
import PropTypes from 'prop-types'
import React, { useEffect, useState } from 'react'
import { render } from 'react-dom'
import * as Sentry from '@sentry/react'
import { useHistory } from 'react-router-dom'

require('./i18n')
require('./icons')
require('../css/imbi.css')
require('typeface-inter')

import { httpGet, isURL } from './utils'
import { Header, Footer } from './components'
import { Error, Initializing, Login, Main } from './views'
import State from './state'

export const loggedOutUser = {
  username: null,
  display_name: null,
  email_address: null,
  user_type: 'internal',
  external_id: null,
  permissions: []
}

function App({
  footerIcon,
  footerText,
  footerUrl,
  ldap,
  logo,
  sentry_dsn,
  service,
  url,
  version
}) {
  if (isURL(sentry_dsn))
    Sentry.init({
      dsn: sentry_dsn,
      release: `imbi@${version}`,
      maxBreadcrumbs: 50
    })
  const [content, setContent] = useState(<Initializing />)
  const [errorMessage, setErrorMessage] = useState(null)
  const history = useHistory()
  const [user, setUser] = useState(loggedOutUser)
  const [userState, setUserState] = useState({
    authenticated: false,
    fetching: false,
    initialized: false
  })

  const authenticatedFetch = (input, init) => {
    return fetch(input, init).then((response) => {
      if (response.status === 401) {
        setUserState({ ...userState, authenticated: false })
        setUser(loggedOutUser)
      }
      return response
    })
  }

  const logout = () => {
    fetch(new URL('/ui/logout', url).toString()).then(() => {
      resetState()
      history.push(`/ui/`)
    })
  }

  const resetState = () => {
    setContent(<Initializing />)
    setUserState({
      authenticated: false,
      fetching: false,
      initialized: false
    })
    setErrorMessage(null)
    setUser({ ...loggedOutUser })
  }

  const setUserData = (data) => {
    delete data.password
    setUser(data)
    setUserState({
      authenticated: true,
      fetching: false,
      initialized: true
    })
  }

  useEffect(() => {
    if (!userState.initialized && userState.fetching === false) {
      // Check if the user is logged in
      setUserState({ ...userState, fetching: true })
      httpGet(
        fetch,
        '/ui/user',
        (result) => {
          setUserData(result)
        },
        () => {
          setUserState({
            authenticated: false,
            fetching: false,
            initialized: true
          })
        }
      )
    } else if (userState.initialized && !userState.authenticated) {
      // Display Login Form
      setContent(
        <Login onLoginCallback={setUserData} useLDAP={ldap === 'true'} />
      )
    } else if (userState.authenticated) {
      setContent(<Main user={user} />)
    }
  }, [user, userState])

  useEffect(() => {
    if (errorMessage !== null) setContent(<Error>{errorMessage}</Error>)
  }, [errorMessage])

  return (
    <State
      baseURL={new URL(url)}
      fetchMethod={authenticatedFetch}
      handleLogout={logout}
      setErrorMessage={setErrorMessage}>
      <Header
        authenticated={userState.authenticated}
        logo={logo}
        service={service}
        user={user}
      />
      {content}
      <Footer
        linkIcon={footerIcon}
        linkText={footerText}
        linkURL={footerUrl}
        service={service}
        version={version}
      />
    </State>
  )
}

App.propTypes = {
  footerIcon: PropTypes.string,
  footerText: PropTypes.string,
  footerUrl: PropTypes.string,
  ldap: PropTypes.string,
  logo: PropTypes.string,
  service: PropTypes.string,
  sentry_dsn: PropTypes.string,
  url: PropTypes.string,
  version: PropTypes.string
}

const root = document.getElementById('app')
render(
  <Router>
    <App {...root.dataset} />
  </Router>,
  root
)
