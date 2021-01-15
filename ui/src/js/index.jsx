import {BrowserRouter as Router} from "react-router-dom"
import PropTypes from "prop-types"
import React, {useEffect, useState} from "react"
import {render} from "react-dom"
import {useHistory} from "react-router-dom"

require("./i18n")
require("./icons")
require("../css/imbi.css")
require("typeface-inter")

import {
  FetchContext,
  LogoutContext,
} from "./contexts"

import {httpGet} from "./utils"
import {Header, Footer} from "./components"
import {Error, Loading, Login, Main} from "./views"

export const loggedOutUser = {
  username: null,
  display_name: null,
  email_address: null,
  user_type: "internal",
  external_id: null,
  permissions: []
}

function App({logo, service, ldap, version}) {
  const [content, setContent] = useState(<Loading />)
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
        setUserState({...userState, authenticated: false})
        setUser(loggedOutUser)
      }
      return response
    })
  }

  const logout = () => {
    fetch('/ui/logout').then(() => {
      resetState()
      history.push(`/ui/`)
    })
  }

  const resetState = () => {
    setContent(<Loading />)
    setErrorMessage(null)
    setUser({...loggedOutUser})
    setUserState({
      authenticated: false,
      fetching: false,
      initialized: false
    })
  }

  const setUserData = (data) => {
    delete data.password
    setUser({
      ...data,
      permissions: data.groups.reduce((accumulator, group) => {
        const permissions = new Set(accumulator)
        group.permissions.map((permission) => {
          permissions.add(permission)
        })
        return Array.from(permissions)
      }, [])
    })
    setUserState({
      authenticated: true,
      fetching: false,
      initialized: true
    })
  }

  useEffect(() => {
    if (!userState.initialized && userState.fetching === false) {
      // Check if the user is logged in
      setUserState({...userState, fetching: true})
      httpGet(
        fetch,
        "/ui/user",
        (result) => {
          setUserData(result)
        },
        () => {
          setUserState({
            authenticated: false,
            fetching: false,
            initialized: true
          })
        })
    } else if (userState.initialized && !userState.authenticated) {
      // Display Login Form
      setContent(<Login onLoginCallback={setUserData}/>)
    } else if (userState.authenticated) {
      // User is logged in, show main content
      setContent(<Main user={user} />)
    }
  }, [user, userState])

  useEffect(() => {
    if (errorMessage !== null)
      setContent(<Error>{errorMessage}</Error>)
  }, [errorMessage])

  return (
    <FetchContext.Provider value={authenticatedFetch}>
        <LogoutContext.Provider value={logout}>
          <Header authenticated={userState.authenticated}
                  logo={logo}
                  service={service}
                  user={user}/>
          {content}
          <Footer service={service} version={version}/>
        </LogoutContext.Provider>
    </FetchContext.Provider>
  )
}

App.propTypes = {
  logo: PropTypes.string,
  service: PropTypes.string,
  ldap: PropTypes.string,
  version: PropTypes.string
}

const root = document.getElementById("app")
render(<Router><App {...(root.dataset)} /></Router>, root)
