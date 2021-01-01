import PropTypes from "prop-types";
import React, {useContext, useRef, useState} from "react"
import {useTranslation} from "react-i18next"

import {Alert} from "../components"
import {FetchContext, SettingsContext, UserContext} from "../contexts"
import {httpPost} from "../utils"

function Login({onLoginCallback}) {

  const {t} = useTranslation()
  const currentUser = useContext(UserContext)
  const fetch = useContext(FetchContext)
  const settings = useContext(SettingsContext)

  const [credentials, setCredentials] = useState({
    username: currentUser.username,
    password: null,
  })
  const [errorMessage, setErrorMessage] = useState(null)
  const [submitting, setSubmitting] = useState(false)

  const usernameRef = useRef()

  function onChange(e) {
    const {name, value} = e.target
    setCredentials({...credentials, [name]: value})
  }

  async function onSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setErrorMessage(null)
    const response = await httpPost(
      fetch,
      "/ui/login",
      {
        username: credentials.username,
        password: credentials.password,
      },
      {credentials: "include"}
    )
    if (response.success === true) {
      onLoginCallback(response.data)
    } else {
      setCredentials({...credentials, password: null})
      setErrorMessage(response.data)
      setSubmitting(false)
      usernameRef.current.focus()
    }
  }

  return (
    <main className="flex flex-row flex-grow overflow-y-auto">
      <div className="container mx-auto my-auto">
        <div className="mt-8 sm:mx-auto sm:w-full sm:max-w-md">
          <div className="bg-white py-8 px-4 shadow sm:rounded-lg sm:px-10">
            <form className="space-y-6" action="#" onSubmit={onSubmit}>
              <div className="rounded-md shadow-sm -space-y-px">
                {errorMessage !== null && (
                  <div className="pb-4">
                    <Alert level="error">{errorMessage}</Alert>
                  </div>
                )}
                <div className="mb-4">
                  <label htmlFor="username"
                         className="block text-sm font-medium text-gray-700 mb-1">
                    {(settings.ldap_enabled ? "LDAP " : "") + "Username"}
                  </label>
                  <input id="username"
                         className={errorMessage !== null ? "form-input-error" : "form-input"}
                         autoFocus
                         name="username"
                         onChange={onChange}
                         ref={usernameRef}
                         required
                         type="text"
                         value={credentials.username !== null ? credentials.username : ""}/>
                </div>
                <div className="mb-4">
                  <label htmlFor="password"
                         className="block text-sm font-medium text-gray-700 mb-1">
                    {t("common.password")}</label>
                  <input id="password"
                         autoComplete="current-password"
                         className={errorMessage !== null ? "form-input-error" : "form-input"}
                         name="password"
                         onChange={onChange}
                         required
                         type="password"
                         value={credentials.password !== null ? credentials.password : ""}/>
                </div>
                <div className="pt-4">
                  <button type="submit"
                          className="btn-blue w-full"
                          disabled={submitting || credentials.username === null || credentials.password === null}>
                    {t("common.login")}
                  </button>
                </div>
              </div>
            </form>
          </div>
        </div>
      </div>
    </main>
  )
}

Login.propTypes = {
  onLoginCallback: PropTypes.func
}

export default Login
