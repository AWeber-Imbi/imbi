import PropTypes from "prop-types"
import React, {useEffect, useState} from "react"
import {render} from "react-dom"
import "./i18n"
import "../css/imbi.css";

import {
  FetchContext,
  SettingsContext,
  UserContext
} from "./contexts"

import {httpGet} from "./utils"
import {Header, Footer} from "./components"
import {Loading, Login, Main} from "./views"

export const loggedOutUser = {
  authenticated: undefined,
  username: null,
  display_name: null,
  email_address: null,
  user_type: "internal",
  external_id: null
}

function App({service, version, logo}) {
  const [currentUser, setCurrentUser] = useState(loggedOutUser)
  const [initialized, setInitialized] = useState({
    settings: false,
    user: false,
  })
  const [settings, setSettings] = useState({service_name: service})

  useEffect(() => {
    if (currentUser.authenticated !== true) {
      httpGet(
        fetch,
        "/ui/user",
        (result) => {
          setCurrentUser({...result, authenticated: true})
          setInitialized({...initialized, user: true})
        },
        (error) => {  // eslint-disable-line no-unused-vars
          setCurrentUser({...loggedOutUser, authenticated: false})
          setInitialized({...initialized, user: true})
        }
      )
    }
  }, [currentUser.username])

  useEffect(() => {
    if (initialized.user === true)
      httpGet(fetch, "/ui/settings", (result) => {
        setSettings(result)
        setInitialized({...initialized, settings: true})
      })
  }, [currentUser.authenticated, initialized.user])

  if (initialized.user === false || initialized.settings === false)
    return (<>
      <Header logo={logo} service={service}/>
      <Loading/>
      <Footer service={service} version={version}/>
    </>)

  return (
    <FetchContext.Provider value={(input, init) => {
      return fetch(input, init).then((response) => {
        if (response.status === 401)
          setCurrentUser({
            ...loggedOutUser,
            authenticated: false,
          })
        return response
      })
    }}>
      <UserContext.Provider value={currentUser}>
        <SettingsContext.Provider value={settings}>
          <Header logo={logo} service={service}/>
          {currentUser.authenticated === false && (<Login onLoginCallback={setCurrentUser}/>)}
          {currentUser.authenticated === true && <Main/>}
          <Footer service={service} version={version}/>
        </SettingsContext.Provider>
      </UserContext.Provider>
    </FetchContext.Provider>
  )
}

App.propTypes = {
  logo: PropTypes.string,
  service: PropTypes.string,
  version: PropTypes.string
}

const root = document.getElementById("app")
render(<App {...(root.dataset)} />, root)
