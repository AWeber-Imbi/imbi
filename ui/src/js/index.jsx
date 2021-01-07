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
  FetchSettingsContext,
  LogoutContext,
  SettingsContext
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
  const [settings, setSettings] = useState({
      service_name: service,
      ldap_enabled: ldap === 'true'
  })
  const [settingsState, setSettingsState] = useState({
    fetch: false,
    fetching: false,
    initialized: false
  })
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

  const fetchSettings = () => {
    setSettingsState({...settingsState, fetch: true})
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
    setSettings({
      service_name: service,
      ldap_enabled: ldap === 'true'
    })
    setSettingsState({
      fetch: false,
      fetching: false,
      initialized: false
    })
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
    } else if (userState.authenticated
               && !settingsState.initialized && !settingsState.fetching && !settingsState.fetch) {
      // Set state to toggle settings fetch
      setSettingsState({...settingsState, fetch: true})
    } else if (settingsState.fetch && !settingsState.fetching) {
      // Fetch settings
      setSettingsState({fetch: false, fetching: true, initialized: false})
      httpGet(
        fetch,
        "/ui/settings",
        (result) => {
          setSettingsState({fetch: false, fetching: false, initialized: true})
          setSettings(result)
        },
        (error) => {
          setSettingsState({fetch: false, fetching: false, initialized: true})
          setErrorMessage(error)
        })
    } else if (settingsState.initialized && userState.authenticated) {
      // User is logged in, show main content
      setContent(<Main user={user} />)
    }
  }, [settingsState, user, userState])

  useEffect(() => {
    if (errorMessage !== null)
      setContent(<Error>{errorMessage}</Error>)
  }, [errorMessage])

  return (
    <FetchContext.Provider value={authenticatedFetch}>
      <FetchSettingsContext.Provider value={fetchSettings}>
        <LogoutContext.Provider value={logout}>
          <SettingsContext.Provider value={settings}>
            <Header authenticated={settingsState.initialized && userState.authenticated}
                    logo={logo}
                    service={service}
                    user={user}/>
            {content}
            <Footer service={service} version={version}/>
          </SettingsContext.Provider>
        </LogoutContext.Provider>
      </FetchSettingsContext.Provider>
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
