import React, { useEffect, useState } from 'react'
import { render } from 'react-dom'
import './i18n'

import {
  FetchContext,
  SettingsContext,
  UserContext
} from './contexts'

import {Loading, Login, Main} from './views'
import {httpGet} from './utils'

export const loggedOutUser = {
    authenticated: undefined,
    username: null,
    display_name: null,
    email_address: null,
    user_type: 'internal',
    external_id: null,
}

function App() {
    const [currentUser, setCurrentUser] = useState(loggedOutUser)
    const [initialized, setInitialized] = useState({
        settings: false,
        user: false,
    })
    const [settings, setSettings] = useState({ service_name: 'Imbi' })

    useEffect(() => {
        if (currentUser.authenticated !== true) {
            httpGet(
                fetch,
                '/ui/user',
                (result) => {
                    setCurrentUser({ ...result, authenticated: true })
                    setInitialized({ ...initialized, user: true })
                },
                (error) => {  // eslint-disable-line no-unused-vars
                    setCurrentUser({ ...loggedOutUser, authenticated: false })
                    setInitialized({ ...initialized, user: true })
                }
            )
        }
    }, [currentUser.username])

    useEffect(() => {
        if (initialized.user === true)
            httpGet(fetch, '/ui/settings', (result) => {
                setSettings(result)
                setInitialized({ ...initialized, settings: true })
            })
    }, [currentUser.authenticated, initialized.user])

    document.body.className =
        currentUser.authenticated !== true ? 'logged-out' : ''

    if (initialized.settings === false || initialized.user === false)
        return <Loading />

    return (
        <FetchContext.Provider
            value={(input, init) => {
                return fetch(input, init).then((response) => {
                    if (response.status == 401)
                        setCurrentUser({
                            ...loggedOutUser,
                            authenticated: false,
                        })
                    return response
                })
            }}
        >
            <UserContext.Provider value={currentUser}>
                <SettingsContext.Provider value={settings}>
                    {currentUser.authenticated === false && (
                        <Login updateUser={setCurrentUser} />
                    )}
                    {currentUser.authenticated === true && <Main />}
                </SettingsContext.Provider>
            </UserContext.Provider>
        </FetchContext.Provider>
    )
}

render(<App />, document.getElementById('app'))
