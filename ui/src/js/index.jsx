import {BrowserRouter as Router} from "react-router-dom"
import PropTypes from "prop-types"
import React, {useEffect, useState} from "react"
import {render} from "react-dom"

import "./i18n"
import "./icons"
import "../css/imbi.css";

import {
  FetchContext,
  FetchSettingsContext,
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
  const [settings, setSettings] = useState({
      service_name: service,
      ldap_enabled: ldap === 'true'
  })
  const [state, setState] = useState({
    settings: {
      fetch: false,
      fetching: false,
      initialized: false
    },
    user: {
      authenticated: false,
      fetching: false,
      initialized: false
    }
  })
  const [user, setUser] = useState(loggedOutUser)

  const authenticatedFetch = (input, init) => {
    return fetch(input, init).then((response) => {
      if (response.status === 401) {
        setState({...state, user: {...state.user, authenticated: false}})
        setUser(loggedOutUser)
      }
      return response
    })
  }

  const fetchSettings = () => {
    setState({...state, settings: {...state.settings, fetch: true}})
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
    setState({
      ...state,
      user: {
        authenticated: true,
        fetching: false,
        initialized: true
      }
    })
  }

  useEffect(() => {
    if (state.user.initialized === false
        && state.user.fetching === false) {
      // Check if the user is logged in
      setState({...state, user: {...state.user, fetching: true}})
      httpGet(
        fetch,
        "/ui/user",
        (result) => {
          setUserData(result)

        },
        () => {
          setState({
            ...state,
            user: {
              authenticated: false,
              fetching: false,
              initialized: true
            }
          })
        })
    } else if (state.user.initialized === true
               && state.user.authenticated === false) {
      // Display Login Form
      setContent(<Login onLoginCallback={setUserData}/>)
    } else if (state.user.authenticated === true
               && state.settings.initialized === false
               && state.settings.fetching === false
               && state.settings.fetch === false) {
      // Set state to toggle settings fetch
      setState({...state, settings: {...state.settings, fetch: true}})
    } else if (state.settings.fetch === true
               && state.settings.fetching === false) {
      // Fetch settings
      setState({...state, settings: {...state.settings, fetching: true}})
      httpGet(
        fetch,
        "/ui/settings",
        (result) => {
          setState({
            ...state,
            settings: {
              ...state.settings,
              fetch: false,
              fetching: false,
              initialized: true
            }})
          setSettings(result)
        },
        (error) => {
          setErrorMessage(error)
          setState({
            ...state,
            settings: {
              ...state.settings,
              fetch: false,
              fetching: false,
              initialized: true
            }})
        })
    } else if (state.settings.initialized === true
               && state.user.authenticated === true) {
      // User is logged in, show main content
      setContent(<Main user={user} />)
    }
  }, [state, user])

  useEffect(() => {
    if (errorMessage !== null)
      setContent(<Error>{errorMessage}</Error>)
  }, [errorMessage])

  return (
    <FetchContext.Provider value={authenticatedFetch}>
      <FetchSettingsContext.Provider value={fetchSettings}>
        <SettingsContext.Provider value={settings}>
          <Header authenticated={state.settings.initialized === true
                                 && state.user.authenticated === true}
                  logo={logo}
                  service={service}
                  user={user}/>
          {content}
          <Footer service={service} version={version}/>
        </SettingsContext.Provider>
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
